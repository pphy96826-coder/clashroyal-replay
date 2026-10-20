"""Malformed/transient maps snapshots, with no device access or memory reads."""
import importlib.util
import ast
import io
from pathlib import Path
import unittest
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('proc_maps_test',ROOT/'device/proc_maps.py')
maps=importlib.util.module_from_spec(spec);spec.loader.exec_module(maps)
GOOD='1000-2000 r--p 00000000 00:00 0\n2000-3000 r-xp 00001000 08:01 123 /data/app/example/base.apk\n'
PROPERTY='49000 r--s 00000000 00:11 398 /dev/__properties__/u:object_r:log_file_logger_prop:s0\n'


class MapsTests(unittest.TestCase):
    def setUp(self):maps._REPORTS.clear()

    def path(self,*values):
        path=Mock();path.open.side_effect=[io.StringIO(v) if isinstance(v,str) else v for v in values]
        return path

    def test_valid_ordinary_and_anonymous_rows(self):
        rows=maps.parse(GOOD)
        self.assertEqual(rows[0][:5],(0x1000,0x2000,'r--p',0,''))
        self.assertEqual(rows[1][4],'/data/app/example/base.apk')

    def test_filename_with_spaces_and_deleted_suffix_is_not_split(self):
        row=maps.parse('1000-2000 rw-p 0 08:01 1 /path/file name (deleted)')[0]
        self.assertEqual(row[4],'/path/file name (deleted)')

    def test_original_unpack_error_becomes_a_structured_failure(self):
        with self.assertRaises(maps.MapsSnapshotError) as error:maps.parse('invalid_row_without_address')
        self.assertEqual(error.exception.detail['line_number'],1)
        self.assertEqual(len(error.exception.detail['line_sha256']),64)

    def test_unknown_or_blank_row_is_never_ignored(self):
        for invalid in ('junk\n'+GOOD,GOOD+'junk\n',GOOD+'\n',GOOD+'\x00\n'):
            with self.assertRaises(maps.MapsSnapshotError):maps.parse(invalid)

    def test_bad_fields_permissions_and_ranges_fail_closed(self):
        for invalid in ('1000 r--p 0 00:00 0','2000-1000 r--p 0 00:00 0',
                        '1000-2000 rwxpz 0 00:00 0','1000-2000 r-xp garbage 00:00 0',
                        '1000-2000 r-xp 0 not-device 0','1000-2000 r-xp 0 00:00 -1',
                        '1000-2000 r-xp 0 00:00 0\n1800-2800 r--p 0 00:00 0',
                        '2000-3000 r-xp 0 00:00 0\n1000-2000 r--p 0 00:00 0'):
            with self.assertRaises(maps.MapsSnapshotError):maps.parse(invalid)

    def test_single_valid_read_needs_no_retry_or_diagnostic(self):
        path=self.path(GOOD);self.assertEqual(maps.read_snapshot(path),GOOD)
        self.assertEqual(path.open.call_count,1);self.assertIsNone(maps.diagnostics())

    def test_transient_bad_read_recovers_from_a_new_complete_snapshot(self):
        path=self.path('junk',GOOD)
        self.assertEqual(maps.read_snapshot(path),GOOD)
        report=maps.diagnostics()['reports'][0]
        self.assertTrue(report['recovered']);self.assertEqual(report['attempts'],2)
        self.assertEqual(maps.diagnostics()['skipped_rows'],0)

    def test_persistent_error_stops_after_three_reads(self):
        path=self.path('junk','junk','junk',GOOD)
        with self.assertRaisesRegex(maps.MapsSnapshotError,'连续3次'):maps.read_snapshot(path)
        self.assertEqual(path.open.call_count,3)
        self.assertFalse(maps.diagnostics()['reports'][0]['recovered'])

    def test_permission_and_io_errors_are_not_retried_or_called_exit(self):
        for error in (PermissionError('denied'),OSError('read error')):
            path=self.path(error,GOOD)
            with self.assertRaises(type(error)):maps.read_snapshot(path)
            self.assertEqual(path.open.call_count,1)

    def test_size_row_and_report_limits(self):
        for text in ('a'*(maps.MAX_TEXT+1),'\n'*(maps.MAX_ROWS+1),''):
            with self.assertRaises(maps.MapsSnapshotError):maps.parse(text)
        for _ in range(12):
            with self.assertRaises(maps.MapsSnapshotError):maps.read_snapshot(self.path('x'*1000,'x'*1000,'x'*1000))
        self.assertEqual(len(maps.diagnostics()['reports']),8)
        self.assertLessEqual(len(maps.diagnostics()['reports'][0]['failures'][0]['line_preview']),240)

    def test_reader_and_exporter_use_the_guarded_snapshot(self):
        reader=(ROOT/'device/device_session.py').read_text()
        self.assertNotIn("(self.proc/'maps').read_text()",reader)
        self.assertIn('for low,high,mode,offset,path,line in parse_maps(maps)',reader)
        java=(ROOT/'app/src/local/royale/replay/android/DiagnosticExport.java').read_text()
        self.assertIn('maps-read-diagnostic.json',java);self.assertIn('maps-diagnostic.json',java)
        runner=(ROOT/'device/device_playback.py').read_text()
        self.assertIn('except MapsSnapshotError:raise',runner)

    def test_known_truncated_property_row_grants_no_address_range(self):
        path=self.path(GOOD+PROPERTY);value=maps.read_snapshot(path)
        self.assertEqual(value,GOOD)
        rows=maps.parse(value);self.assertEqual(len(rows),2)
        self.assertFalse(any(low<=0x49000<high for low,high,*_ in rows))
        report=maps.diagnostics();self.assertEqual(report['unknown_rows_skipped'],0)
        self.assertEqual(report['skipped_rows'],1);self.assertFalse(report['excluded_records_authorize_memory'])
        record=report['reports'][0]['excluded_property_records'][0]
        self.assertFalse(record['authorized_range']);self.assertEqual(record['line_number'],3)
        self.assertEqual(path.open.call_count,1)

    def test_property_exclusion_never_fills_a_gap_between_valid_ranges(self):
        text='1000-2000 r--p 0 00:00 0\n'+PROPERTY+'3000-4000 r--p 0 00:00 0\n'
        rows=maps.parse(maps.read_snapshot(self.path(text)))
        self.assertEqual([(r[0],r[1]) for r in rows],[(0x1000,0x2000),(0x3000,0x4000)])

    def test_near_matches_writable_executable_private_or_nonproperty_rows_still_fail(self):
        for line in (PROPERTY.replace('r--s','rw-s'),PROPERTY.replace('r--s','r-xs'),
                     PROPERTY.replace('r--s','r--p'),PROPERTY.replace('00000000','00001000'),
                     PROPERTY.replace('/dev/__properties__/','/data/app/'),
                     PROPERTY.replace(':s0',':s0 (deleted)'),PROPERTY.replace('49000','49000-'),
                     PROPERTY.replace(':s0',':s0 /extra')):
            with self.assertRaises(maps.MapsSnapshotError):maps.parse(GOOD+line)

    def test_fully_formed_property_mapping_remains_an_ordinary_mapping(self):
        line=PROPERTY.replace('49000 ','4000-5000 ',1)
        value=maps.read_snapshot(self.path(GOOD+line))
        self.assertEqual(value,GOOD+line);self.assertEqual(len(maps.parse(value)),3)
        self.assertIsNone(maps.diagnostics())

    def test_excluding_properties_cannot_hide_unordered_or_unknown_rows(self):
        for text in (GOOD+PROPERTY+'unknown\n',GOOD+PROPERTY+'1800-2800 r--p 0 00:00 0\n'):
            with self.assertRaises(maps.MapsSnapshotError):maps.parse(text)

    def test_only_property_rows_or_excessive_exclusions_are_not_usable_maps(self):
        for text in (PROPERTY,GOOD+PROPERTY*33):
            with self.assertRaises(maps.MapsSnapshotError):maps.parse(text)

    def test_resource_reader_cannot_read_the_excluded_record_or_bridge_its_gap(self):
        tree=ast.parse((ROOT/'device/device_session.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='checked_range')
        scope={'MASK':0x00ffffffffffffff}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'bounded-read-test','exec'),scope)
        text='1000-2000 r--p 0 00:00 0\n'+PROPERTY+'3000-4000 r--p 0 00:00 0\n'
        ranges=[row[:3] for row in maps.parse(maps.read_snapshot(self.path(text)))]
        self.assertEqual(scope['checked_range'](0x1000,4,ranges,0),0x1000)
        for address,size in ((0x49000,4),(0x1800,4096)):
            with self.assertRaisesRegex(ValueError,'not readable'):
                scope['checked_range'](address,size,ranges,0)


if __name__=='__main__':unittest.main()
