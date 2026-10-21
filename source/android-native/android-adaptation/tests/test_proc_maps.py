"""Malformed/transient maps snapshots, with no device access or memory reads."""
import importlib.util
import ast
import io
from pathlib import Path
import unittest
from unittest import mock
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
        for invalid in ('junk\n'+GOOD,GOOD+'junk\n',GOOD+'\n3000-4000 r--p 0 00:00 0\n',GOOD+'\n\n','\n'+GOOD,GOOD+'\x00\n'):
            with self.assertRaises(maps.MapsSnapshotError):maps.parse(invalid)

    def test_bad_fields_permissions_and_ranges_fail_closed(self):
        for invalid in ('1000 r--p 0 00:00 0','2000-1000 r--p 0 00:00 0',
                        '1000-2000 rwxpz 0 00:00 0','1000-2000 r-xp garbage 00:00 0',
                        '1000-2000 r-xp 0 not-device 0','1000-2000 r-xp 0 00:00 -1',
                        '1000-2000 r-xp 0 00:00 0\n1800-2800 r--p 0 08:01 5 /system/lib64/libc.so',
                        '2000-3000 r-xp 0 00:00 0\n1000-2000 r--p 0 08:01 5 /data/app/x/base.apk',
                        '3000-4000 r-xp 0 00:00 0\n2000-1000 r--p 0 00:00 0'):
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
        record=report['reports'][0]['excluded_fragments'][0]
        self.assertFalse(record['authorized_range']);self.assertEqual(record['line_number'],3)
        self.assertEqual(path.open.call_count,1)

    def test_property_exclusion_never_fills_a_gap_between_valid_ranges(self):
        text='1000-2000 r--p 0 00:00 0\n'+PROPERTY+'3000-4000 r--p 0 00:00 0\n'
        rows=maps.parse(maps.read_snapshot(self.path(text)))
        self.assertEqual([(r[0],r[1]) for r in rows],[(0x1000,0x2000),(0x3000,0x4000)])

    def test_near_matches_file_backed_or_malformed_rows_still_fail(self):
        for line in (PROPERTY.replace('/dev/__properties__/','/data/app/'),
                     PROPERTY.replace('/dev/__properties__/u:object_r:log_file_logger_prop:s0','/system/lib64/libc.so'),
                     PROPERTY.replace(':s0',':s0 (deleted)'),PROPERTY.replace('49000','49000-'),
                     PROPERTY.replace(':s0',':s0 /extra')):
            with self.assertRaises(maps.MapsSnapshotError):maps.parse(GOOD+line)

    def test_observed_vm_libc_malloc_fragment_is_excluded_with_context(self):
        # 虚拟大师 Android 12 guest, line 5402 of the game's maps, identical on 3 reads.
        frag=':38 42                             [anon:libc_malloc]\n'
        path=self.path(GOOD+frag+'3000-4000 r--p 0 00:00 0\n');value=maps.read_snapshot(path)
        self.assertEqual(value,GOOD+'3000-4000 r--p 0 00:00 0\n')
        record=maps.diagnostics()['reports'][0]['excluded_fragments'][0]
        self.assertEqual(record['reason'],'head_truncated_fragment');self.assertFalse(record['authorized_range'])
        self.assertEqual(record['line_number'],3);self.assertEqual(record['byte_offset'],len(GOOD.encode()))
        self.assertTrue(record['previous_preview'].startswith('2000-'))
        self.assertTrue(record['next_preview'].startswith('3000-4000'))

    def test_head_cut_at_any_field_before_the_inode_is_a_fragment_for_anonymous_names(self):
        row='7a1c2000-7a1c3000 rw-p 00000000 00:00 0                          [anon:libc_malloc]'
        for cut in range(row.index(' ')+1,row.index(' 0 ')+1):
            fragment=row[cut:]
            if not fragment or fragment[0]==' ':continue
            self.assertTrue(maps._truncated_fragment(fragment),fragment)
        for name in ('','[heap]','[stack]','[anon:scudo:primary]'):
            self.assertTrue(maps._truncated_fragment('p 00000000 00:00 0 '+name))

    def test_file_backed_unknown_or_complete_rows_are_never_fragments(self):
        for line in ('xp 00001000 fd:01 1234 /data/app/x/lib/arm64/libg.so','00 fd:01 1234 /system/lib64/libc.so',
                     '1000-2000 r--p 0 00:00 0','1000-2000 rw-p 0 00:00 0 [anon:x]','junk','','0 [anon:x]',
                     ':38 42 [anon:x] extra',':38 42 [anon:'+'x'*97+']','rw-q 0 00:00 0','ZZ:01 7'):
            self.assertFalse(maps._truncated_fragment(line),line)
        with self.assertRaises(maps.MapsSnapshotError) as caught:
            maps.parse(GOOD+'xp 00001000 fd:01 1234 /data/app/x/base.apk\n')
        self.assertEqual(caught.exception.detail['reason'],'invalid_or_unordered_row')
        self.assertIn('previous_preview',caught.exception.detail)

    def test_observed_vm_tail_after_stack_is_excluded_without_granting_ranges(self):
        # 虚拟大师 Android 12 guest: rows appended after [stack], out of order,
        # one with its start address cut ("78be5" lost).
        stack='7fc6451000-7fc6c50000 rw-p 00000000 00:00 0                              [stack]\n'
        tail=('67000-78be576000 ---p 00000000 00:00 0 \n'
              '78be576000-78be577000 r--p 00020000 07:38 36                             [anon:libc_malloc]\n'
              ':38 42                             [anon:libc_malloc]\n')
        value=maps.read_snapshot(self.path(GOOD+stack+tail))
        self.assertEqual(value,GOOD+stack)
        rows=maps.parse(value);self.assertEqual(len(rows),3)
        self.assertFalse(any(low<=0x78be576000<high or low<=0x67000<high for low,high,*_ in rows))
        reasons=[r['reason'] for r in maps.diagnostics()['reports'][0]['excluded_fragments']]
        self.assertEqual(reasons,['unordered_anonymous_row','unordered_anonymous_row','head_truncated_fragment'])
        self.assertTrue(all(not r['authorized_range'] for r in maps.diagnostics()['reports'][0]['excluded_fragments']))

    def test_vm_replay_of_the_file_tail_is_dropped_even_mid_file_backed_row(self):
        # 虚拟大师: after [stack] the last stretch is emitted again from mid-line.
        body=('1000-2000 r--p 00000000 00:00 0\n'
              '78be797000-78be7a1000 r-xp 00010000 07:38 42                             [anon:libc_malloc]\n'
              '78be7a1000-78be7a7000 r-xp 00001000 fd:05 77 /data/app/x/lib/arm64/libg.so\n'
              '7fc6451000-7fc6c50000 rw-p 00000000 00:00 0                              [stack]\n')
        lines=body.splitlines(True)
        replay=lines[2][9:]+lines[3]+'0 07:38 42                             [anon:libc_malloc]\n'+lines[3]
        value=maps.read_snapshot(self.path(body+replay))
        self.assertEqual(value,body)
        rows=maps.parse(value);self.assertEqual(len(rows),4)
        excluded=maps.diagnostics()['reports'][0]['excluded_fragments']
        self.assertEqual([e['reason'] for e in excluded],['replayed_line']*4+['replayed_line_total'])
        self.assertEqual(excluded[-1]['count'],4)

    def test_blank_line_opening_a_replayed_block_is_dropped(self):
        # 虚拟大师 hotfix15 run: [stack], a blank line, then earlier rows again.
        body=('1000-2000 r--p 00000000 00:00 0\n'
              '78bda8b000-78bda91000 ---p 00000000 00:00 0 \n'
              '78bda91000-78bda97000 r-xp 00010000 fe:01 586                            [anon:libc_malloc]\n'
              '7fc6451000-7fc6c50000 rw-p 00000000 00:00 0                              [stack]\n')
        lines=body.splitlines(True)
        value=maps.read_snapshot(self.path(body+'\n'+lines[1]+lines[2]))
        self.assertEqual(value,body);self.assertEqual(len(maps.parse(value)),4)
        # hotfix20 run: one extra final newline after [stack] is accepted.
        self.assertEqual(len(maps.parse(body+'\n')),4)
        for text in (body+'\n\n',body+'\n\n'+lines[1],body+'\nunknown\n','\n'+body):
            with self.assertRaises(maps.MapsSnapshotError):maps.parse(text)

    def test_line_that_is_not_a_copy_of_an_accepted_row_still_fails(self):
        body='1000-2000 r--p 0 00:00 0\n3000-4000 r-xp 0 fd:05 77 /data/app/x/lib/arm64/libg.so\n'
        for extra in ('2000-3000 r-xp 0 fd:05 77 /data/app/x/lib/arm64/libh.so\n','libg.so extra\n','4000-5000 r-xp 0 fd:05 77 /data/app/x/lib/arm64/libg.so\n'[:-1]+'x\n'):
            text=body+extra if not extra.startswith('4000') else body+'1800-1900 r-xp 0 fd:05 77 /data/app/x/lib/arm64/libgx.so\n'
            with self.assertRaises(maps.MapsSnapshotError):maps.parse(text)

    def test_failure_report_is_kept_after_many_recoveries(self):
        stack='7fc6451000-7fc6c50000 rw-p 00000000 00:00 0 [stack]\n'
        for index in range(12):
            maps.read_snapshot(self.path(GOOD+stack+stack[index%5:]))
        with self.assertRaises(maps.MapsSnapshotError):maps.read_snapshot(self.path('junk\n','junk\n','junk\n'))
        reports=maps.diagnostics()['reports']
        self.assertLessEqual(len(reports),8);self.assertFalse(reports[-1]['recovered'])
        self.assertTrue(any(r.get('occurrences',1)>1 for r in reports if r['recovered']))

    def test_large_replay_parses_quickly(self):
        import time
        body=''.join('%x-%x rw-p 00000000 00:00 0 [anon:x]\n'%(0x10000+i*0x1000,0x10000+i*0x1000+0x800) for i in range(6000))
        tail=''.join(body.splitlines(True)[-1500:])
        start=time.monotonic();rows=maps.parse(body+tail[7:])
        self.assertEqual(len(rows),6000);self.assertLess(time.monotonic()-start,2.0)

    def test_unordered_file_backed_row_fails_with_tail_context(self):
        text=GOOD+'7fc6451000-7fc6c50000 rw-p 0 00:00 0 [stack]\n78be576000-78be577000 r-xp 0 07:38 36 /data/app/x/base.apk\n'
        with self.assertRaises(maps.MapsSnapshotError) as caught:maps.parse(text)
        detail=caught.exception.detail
        self.assertEqual(detail['reason'],'invalid_or_unordered_row');self.assertEqual(len(detail['tail_preview']),4)

    def test_reader_asks_for_the_whole_capped_file_unbuffered_and_records_calls(self):
        stream=mock.MagicMock();stream.__enter__.return_value=stream
        stream.read.side_effect=[GOOD[:10].encode(),GOOD[10:].encode(),b'']
        path=mock.Mock();path.open.return_value=stream
        self.assertEqual(maps.read_snapshot(path),GOOD)
        path.open.assert_called_once_with('rb',buffering=0)
        self.assertEqual(stream.read.call_args_list[0],mock.call(maps.MAX_TEXT+1))
        self.assertEqual(stream.read.call_args_list[1],mock.call(maps.MAX_TEXT+1-10))
        bad=mock.MagicMock();bad.__enter__.return_value=bad;bad.read.side_effect=[b'junk\n',b'']*3
        path=mock.Mock();path.open.return_value=bad
        with self.assertRaises(maps.MapsSnapshotError):maps.read_snapshot(path)
        failure=maps.diagnostics()['reports'][-1]['failures'][0]
        self.assertEqual(failure['read_calls'],[5]);self.assertEqual(failure['read_bytes'],5)

    def test_fully_formed_property_mapping_remains_an_ordinary_mapping(self):
        line=PROPERTY.replace('49000 ','4000-5000 ',1)
        value=maps.read_snapshot(self.path(GOOD+line))
        self.assertEqual(value,GOOD+line);self.assertEqual(len(maps.parse(value)),3)
        self.assertIsNone(maps.diagnostics())

    def test_excluding_properties_cannot_hide_unordered_or_unknown_rows(self):
        for text in (GOOD+PROPERTY+'unknown\n',GOOD+PROPERTY+'1800-2800 r--p 0 08:01 5 /system/lib64/libc.so\n'):
            with self.assertRaises(maps.MapsSnapshotError):maps.parse(text)

    def test_only_property_rows_or_excessive_exclusions_are_not_usable_maps(self):
        for text in (PROPERTY,GOOD+PROPERTY*65):
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
