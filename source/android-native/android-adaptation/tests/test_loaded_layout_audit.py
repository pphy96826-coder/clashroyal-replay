"""Meaningful checks for ARM64 field moves and fail-closed read-only capture."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from audit_runtime_layout import audit, compare_loaded, member_operand, summarize
from read_client_candidates import Snapshot, capture, start_time, validate_candidates


def words(*values):
    return struct.pack('<'+'I'*len(values), *values)


def function(offset=0x220):
    load = 0xf9400260 | ((offset//8) << 10)  # LDR X0, [X19, #offset]
    return words(0xaa0003f3, load, 0x94000003, load, 0xd65f03c0)


class LayoutTests(unittest.TestCase):
    def test_relocated_branches_are_not_member_changes(self):
        a = words(0xaa0003f3, 0x94000100, 0xd65f03c0)
        b = words(0xaa0003f3, 0x94001000, 0xd65f03c0)
        result = compare_loaded(a, b)
        self.assertTrue(result['normalized_equal'])
        self.assertEqual(result['member_changes'], [])

    def test_real_member_displacement_remains_visible(self):
        result = compare_loaded(function(), function(0x228))
        self.assertFalse(result['normalized_equal'])
        self.assertEqual(result['unexplained_instruction_changes'], 0)
        self.assertEqual(len(result['member_changes']), 2)
        for row in result['member_changes']:
            self.assertEqual((row['old_member_offset'], row['new_member_offset']), ('0x220', '0x228'))
        self.assertFalse(result['native_execution_allowed'])

    def test_object_register_must_be_proved_in_both_functions(self):
        a = function().replace(words(0xaa0003f3), words(0xd503201f))
        result = compare_loaded(a, function(0x228))
        self.assertFalse(result['self_register_bound'])
        self.assertEqual(result['member_changes'], [])
        self.assertGreater(result['unexplained_instruction_changes'], 0)

    def test_reusing_self_register_for_a_temporary_ends_object_proof(self):
        a=words(0xaa0003f3, 0x2a0003f3, 0xf9411260, 0xd65f03c0)
        b=words(0xaa0003f3, 0x2a0003f3, 0xf9411660, 0xd65f03c0)
        result=compare_loaded(a,b)
        self.assertEqual(result['member_changes'], [])
        self.assertEqual(result['unexplained_instruction_changes'], 1)

    def test_load_width_operation_and_base_are_not_masked(self):
        before = member_operand(0xf9411260)
        for other in (0xb9411260, 0xf9011660, 0xf9411680):
            self.assertNotEqual(before['shape'], member_operand(other)['shape'])
        self.assertIsNone(member_operand(0x3dc08a60))  # SIMD Q load
        self.assertIsNone(member_operand(0x58000000))  # PC-relative literal

    def test_field_pointer_add_instead_of_only_loads(self):
        a = words(0xaa0003f3, 0x91028260, 0xd65f03c0)
        b = words(0xaa0003f3, 0x91029260, 0xd65f03c0)
        result = compare_loaded(a, b)
        self.assertEqual(result['member_changes'][0]['kind'], 'member_address')
        self.assertEqual(result['member_changes'][0]['new_member_offset'], '0xa4')

    def test_new_instructions_are_unexplained_not_silently_accepted(self):
        result = compare_loaded(function(), words(0xd503201f)+function())
        self.assertEqual(result['unexplained_instruction_changes'], 1)
        self.assertFalse(result['native_execution_allowed'])

    def test_repeated_reference_is_not_independent_confirmation(self):
        row = dict(name='bootstrap', comparison=compare_loaded(function(), function(0x228)))
        self.assertFalse(summarize([row])[0]['corroborated'])
        step = dict(name='step', comparison=row['comparison'])
        self.assertTrue(summarize([row, step])[0]['corroborated'])
        conflict = dict(name='third', comparison=compare_loaded(function(), function(0x230)))
        self.assertTrue(all(x['conflicting'] for x in summarize([row, step, conflict])))

    def test_capture_integrity_checked_and_unknown_adapter_never_enabled(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            (path/'old.bin').write_bytes(function())
            (path/'new.bin').write_bytes(function(0x228))
            def spec(name, value):
                return dict(file=name, va='0x1000', bytes=len(value), sha256=hashlib.sha256(value).hexdigest())
            old = dict(schema='royale-replay.loaded-reference.v1', library_sha256='a'*64,
                       functions=dict(bootstrap=spec('old.bin', function())))
            new = dict(schema='royale-replay.loaded-code-snapshot.v1', library_sha256='b'*64,
                       native_calls=False, game_memory_written=False, generation_verified=True,
                       functions=dict(bootstrap=spec('new.bin', function(0x228))))
            (path/'old.json').write_text(json.dumps(old)); (path/'new.json').write_text(json.dumps(new))
            result = audit(path/'old.json', path/'new.json')
            self.assertFalse(result['object_layout_verified'])
            self.assertFalse(result['native_execution_allowed'])
            (path/'new.bin').write_bytes(function())
            with self.assertRaisesRegex(ValueError, 'hash differs'):
                audit(path/'old.json', path/'new.json')
            new['functions']['bootstrap']['file'] = '../new.bin'
            (path/'new.json').write_text(json.dumps(new))
            with self.assertRaisesRegex(ValueError, 'sibling'):
                audit(path/'old.json', path/'new.json')


class CaptureTests(unittest.TestCase):
    def test_capture_writes_private_complete_receipt_only_after_final_verification(self):
        class FakeSnapshot:
            def __init__(self, *args):
                self.library_sha256='a'*64; self.apk_sha256='b'*64
                self.pid='123'; self.start='456'; self.used=0
            def read(self, va, size):
                self.used += 2*size
                return b'\0'*size
            def verify(self):
                pass
        doc = dict(schema='royale-replay.code-candidates.v1', library_sha256='a'*64,
                   functions={'test': dict(va='0x1000', bytes=32)})
        with tempfile.TemporaryDirectory() as temp, patch('read_client_candidates.Snapshot', FakeSnapshot):
            destination = Path(temp)/'complete'
            result = capture({}, Path('unused'), doc, destination)
            self.assertEqual(result['read_bytes'], 64)
            self.assertEqual((destination/'snapshot.json').stat().st_mode & 0o777, 0o600)
            self.assertEqual((destination/'test.bin').stat().st_mode & 0o777, 0o600)
            self.assertEqual(destination.stat().st_mode & 0o777, 0o700)
            with patch.object(FakeSnapshot, 'verify', side_effect=ValueError('generation changed')):
                with self.assertRaisesRegex(ValueError, 'generation changed'):
                    capture({}, Path('unused'), doc, Path(temp)/'incomplete')
                self.assertFalse((Path(temp)/'incomplete/snapshot.json').exists())

    def test_budget_counts_stability_reread(self):
        doc = dict(schema='royale-replay.code-candidates.v1', library_sha256='a'*64,
                   functions={f'func{i}': dict(va=hex(0x1000+i*4096), bytes=4096) for i in range(8)})
        self.assertEqual(validate_candidates(doc), 65536)
        doc['functions']['ninth'] = dict(va='0x9000', bytes=4)
        with self.assertRaisesRegex(ValueError, 'budget'):
            validate_candidates(doc)

    def test_bad_ranges_and_names_rejected_before_reading(self):
        for name, va, size in [('f', '0x1001', 32), ('../private', '0x1000', 32),
                               ('f', '0x1000', True), ('f', '0x1000', 8192)]:
            with self.subTest(name=name, va=va, size=size):
                with self.assertRaises(ValueError):
                    validate_candidates(dict(schema='royale-replay.code-candidates.v1',
                                             library_sha256='a'*64,
                                             functions={name: dict(va=va, bytes=size)}))

    def test_generation_parses_names_with_spaces_and_parentheses(self):
        self.assertEqual(start_time(b'12 (game (test)) S '+b'0 '*18+b'123 0 0'), '123')
        with self.assertRaises(ValueError):
            start_time(b'12 (game) S')

    def test_out_of_budget_and_out_of_mapping_never_call_adb(self):
        session = object.__new__(Snapshot)
        session.base = 0x100000; session.end = 0x110000; session.used = 65530
        with patch('read_client_candidates.subprocess.run') as run:
            for va, size in [(0x100, 4), (0x10000, 4), (0, 4), (0x100, 4097)]:
                with self.assertRaises(ValueError):
                    session.read(va, size)
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
