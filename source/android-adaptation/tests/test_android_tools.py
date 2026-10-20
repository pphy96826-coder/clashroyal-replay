import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('stage_android_tools',ROOT/'scripts/stage_android_tools.py')
tools=importlib.util.module_from_spec(spec);spec.loader.exec_module(tools)


def archive(member):
    buffer=io.BytesIO()
    with tarfile.open(fileobj=buffer,mode='w:xz') as output:output.addfile(member,io.BytesIO(b'test') if member.isfile() else None)
    data=buffer.getvalue()
    header=('data.tar.xz/'.ljust(16)+'0'.ljust(12)+'0'.ljust(6)+'0'.ljust(6)+'100644'.ljust(8)+str(len(data)).ljust(10)+'`\n').encode()
    return b'!<arch>\n'+header+data+(b'\n' if len(data)%2 else b'')


class AndroidToolArchiveTests(unittest.TestCase):
    def test_rejects_non_debian_input(self):
        with self.assertRaises(ValueError):tools.ar_data(b'not a package')

    def test_rejects_truncated_ar(self):
        item=tarfile.TarInfo('data/data/com.termux/files/usr/lib/test');item.size=4
        with self.assertRaises(ValueError):tools.ar_data(archive(item)[:-100])

    def test_rejects_archive_escape(self):
        item=tarfile.TarInfo('../escape');item.size=4
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):tools.extract(archive(item),Path(directory),'test')

    def test_rejects_link_escape(self):
        item=tarfile.TarInfo('data/data/com.termux/files/usr/lib/test');item.type=tarfile.SYMTYPE;item.linkname='../../../../escape'
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):tools.extract(archive(item),Path(directory),'test')

    def test_conflicting_binary_is_not_overwritten(self):
        item=tarfile.TarInfo('data/data/com.termux/files/usr/lib/test');item.size=4
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'lib').mkdir();(root/'lib/test').write_bytes(b'keep')
            with self.assertRaises(ValueError):tools.extract(archive(item),root,'test')
            self.assertEqual((root/'lib/test').read_bytes(),b'keep')


if __name__=='__main__':unittest.main()
