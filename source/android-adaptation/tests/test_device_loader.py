"""Synthetic mappings only; these tests do not attach to a game."""
import hashlib
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('device_loader_test', ROOT/'device/device_loader.py')
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)
RAW = bytes(range(256))*32


class Elf:
    def __init__(self, raw):
        if raw != RAW:
            raise ValueError('bad ELF')
        self.raw = raw
        self.phoff = 64
        # Two different VA segments share the same file offset on purpose.
        self.programs = [(1, 4, 0, 0, 0, 256, 4096, 4096),
                         (1, 5, 0, 4096, 0, 512, 4096, 4096),
                         (1, 6, 4096, 8192, 0, 128, 4096, 4096)]

    def slice(self, offset, size):
        return self.raw[offset:offset+size]

    def at(self, va, size):
        return self.raw[va-4096:va-4096+size]

    def exports(self, names):
        return {name: dict(va=hex(4096+256+i*16), size=16,
                          sha256=hashlib.sha256(RAW[256+i*16:272+i*16]).hexdigest())
                for i, name in enumerate(sorted(names))}


def maps(base=0x100000, path='/apex/com.android.runtime@123/lib64/bionic/libdl.so', inode=42):
    return '\n'.join(f'{base+i*4096:x}-{base+(i+1)*4096:x} {mode} {offset:08x} 08:01 {inode} {path}'
                     for i, mode, offset in ((0, 'r--p', 0), (1, 'r-xp', 0), (2, 'rw-p', 4096)))


class Session:
    def __init__(self, text=None, corrupt=False):
        self.text = text or maps()
        self.proc = Path('/proc/123')
        self.used = 64
        self.identity = {'pid': 123}
        self.corrupt = corrupt

    def verify(self):
        return self.text

    def read_many(self, ranges):
        rows = [row for group in loader.loader_groups(self.text.splitlines()) for row in group['rows']]
        result = []
        for address, size in ranges:
            matches = [row for row in rows if row[0] <= address and address+size <= row[1]]
            if len(matches) != 1:
                raise ValueError('not readable')
            low, high, offset, mode = matches[0]
            data = RAW[offset+address-low:offset+address-low+size]
            result.append(bytes(size) if self.corrupt else data)
            self.used += size
        return result


class LoaderTests(unittest.TestCase):
    def resolve(self, session):
        return loader.resolve_loader(session, Elf, page=4096, read_file=lambda path: RAW)

    def test_two_zero_offsets_are_one_object(self):
        result, diagnostic = self.resolve(Session())
        self.assertEqual(result['base'], '0x100000')
        self.assertEqual(diagnostic['verified_candidates'], 1)
        self.assertEqual(diagnostic['candidates'][0]['zero_offset_rows'], 2)
        self.assertIn('@123', result['library'])

    def test_alias_rows_share_file_identity(self):
        text = maps().splitlines()
        text[1] = text[1].replace('/apex/com.android.runtime@123/lib64/bionic/libdl.so',
                                '/system/lib64/libdl.so')
        result, diagnostic = self.resolve(Session('\n'.join(text)))
        self.assertEqual(diagnostic['mapped_objects'], 1)
        self.assertEqual(result['base'], '0x100000')

    def test_target_mount_namespace_file_fallback(self):
        def read_file(path):
            if not path.startswith('/proc/123/root/'):
                raise FileNotFoundError()
            return RAW
        result, diagnostic = loader.resolve_loader(Session(), Elf, page=4096, read_file=read_file)
        self.assertTrue(result['library'].startswith('/proc/123/root/'))

    def test_real_ambiguity_is_not_first_match(self):
        for text in (maps()+'\n'+maps(0x200000),
                     maps()+'\n'+maps(0x200000, inode=43)):
            with self.assertRaisesRegex(loader.LoaderResolutionError, 'verified candidates=2'):
                self.resolve(Session(text))

    def test_missing_library_and_wrong_live_bytes_fail_closed(self):
        for session in (Session('1000-2000 r-xp 0 08:01 42 /system/lib64/libc.so'),
                        Session(corrupt=True)):
            with self.assertRaisesRegex(loader.LoaderResolutionError, 'verified candidates=0'):
                self.resolve(session)

    def test_partial_segments_and_non_executable_code_rejected(self):
        for text in ('\n'.join(maps().splitlines()[:2]), maps().replace('r-xp', 'r--p')):
            with self.assertRaises(loader.LoaderResolutionError):
                self.resolve(Session(text))

    def test_read_budget_remains_bounded(self):
        session = Session()
        session.used = 61400
        with self.assertRaisesRegex(loader.LoaderResolutionError, 'budget exhausted'):
            self.resolve(session)
        self.assertEqual(session.used, 61400)

    def test_mapping_race_rejected_after_reads(self):
        session = Session()
        session.verify = lambda: session.text if session.used == 64 else session.text.replace('r-xp', 'r--p')
        with self.assertRaisesRegex(loader.LoaderResolutionError, 'mappings changed'):
            self.resolve(session)

    def test_unrelated_mapping_change_does_not_invalidate_loader(self):
        session = Session()
        session.verify = lambda: session.text if session.used == 64 else (
            session.text+'\n500000-501000 rw-p 0 00:00 0 [anon:heap]')
        result, diagnostic = self.resolve(session)
        self.assertEqual(diagnostic['verified_candidates'], 1)

    def test_16k_page_geometry(self):
        elf = Elf(RAW)
        elf.programs = [(1, 5, 0, 0, 0, 8192, 16384, 16384)]
        self.assertEqual(loader.load_biases([(0x100000, 0x104000, 0, 'r-xp')], elf, 16384), [0x100000])

    def test_diagnostics_exclude_process_map_and_addresses(self):
        with self.assertRaises(loader.LoaderResolutionError) as error:
            self.resolve(Session(corrupt=True))
        self.assertNotIn('0x100000', str(error.exception.diagnostic))
        self.assertNotIn('100000-101000', str(error.exception.diagnostic))


if __name__ == '__main__':
    unittest.main()
