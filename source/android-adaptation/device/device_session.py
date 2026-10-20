"""Phone-local, read-only resource transport for the audited native observers.

Only the installed pinned game, exact process generation, mapped ranges and
64KiB/session are allowed. No ADB, ptrace, native calls, socket or memory writes.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import zipfile
from proc_maps import parse as parse_maps,read_snapshot

MASK = 0x00ffffffffffffff
CONTRACT = json.loads((Path(__file__).parent/'native-contract.json').read_text())


def start_time(text):
    close = text.rfind(')')
    fields = text[close+1:].split()
    if close < 0 or len(fields) <= 19 or not fields[19].isdigit():
        raise ValueError('invalid process generation')
    return fields[19]


def checked_range(address, size, mappings, used):
    if type(address) is not int or type(size) is not int:
        raise ValueError('integer bounded range required')
    address &= MASK
    if not 0 < size <= 4096 or used+size > 65536:
        raise ValueError('native resource read budget exceeded')
    covered = address
    for low, high, mode in mappings:
        if high <= covered:
            continue
        if low > covered or 'r' not in mode:
            break
        covered = high
        if covered >= address+size:
            return address
    raise ValueError('native resource range is not readable')


def installed_library(apk):
    if not re.fullmatch(r'/data/app/[A-Za-z0-9_=./+~\-]+/base\.apk', str(apk)):
        raise ValueError('not an installed base APK')
    with zipfile.ZipFile(apk) as archive:
        item = archive.getinfo('lib/arm64-v8a/libg.so')
        if item.file_size != CONTRACT['library_bytes'] or item.compress_type != zipfile.ZIP_STORED:
            raise ValueError('installed library layout differs')
        raw = archive.read(item)
    if hashlib.sha256(raw).hexdigest() != CONTRACT['library_sha256']:
        raise ValueError('installed library hash differs; no native reads permitted')
    with open(apk, 'rb') as stream:
        stream.seek(item.header_offset)
        header = stream.read(30)
    if len(header) != 30 or header[:4] != b'PK\x03\x04':
        raise ValueError('invalid installed ZIP header')
    names, extra = struct.unpack_from('<HH', header, 26)
    offset = item.header_offset+30+names+extra
    if offset % 4096:
        raise ValueError('installed mapping offset is not page aligned')
    return offset


def bind(apk):
    if os.getuid() != 0:
        raise PermissionError('existing per-app root grant required; no bypass')
    offset = installed_library(apk)
    value = subprocess.check_output(['/system/bin/pidof', CONTRACT['package']], text=True, timeout=5).strip()
    if not re.fullmatch(r'[1-9][0-9]{0,6}', value):
        raise ValueError('exactly one installed game process required')
    pid = int(value)
    proc = Path('/proc')/value
    if (proc/'cmdline').read_bytes().split(b'\0')[0] != CONTRACT['package'].encode():
        raise ValueError('game process name differs')
    before = start_time((proc/'stat').read_text())
    status = (proc/'status').read_text()
    if 'TracerPid:\t0' not in status.splitlines():
        raise ValueError('existing debugger owns game; no duplicate observation')
    maps = read_snapshot(proc/'maps')
    rows = [row[5] for row in parse_maps(maps) if row[2]=='r-xp' and row[3]==offset and row[4]==str(apk)]
    if len(rows) != 1:
        raise ValueError('installed game mapping is absent or ambiguous')
    low, high = (int(x, 16) for x in rows[0].split()[0].split('-'))
    if high-low != CONTRACT['executable_span'] or low % 4096:
        raise ValueError('audited executable span differs')
    identity = dict(pid=pid, process_start_time=before, apk=str(apk),
                    base=hex(low), executable_end=hex(high), mapping=rows[0],
                    library_sha256=CONTRACT['library_sha256'], jni_exports=CONTRACT['jni_exports'],
                    processing_location='android', desktop_backend_used=False)
    session = ReadOnlySession(identity)
    session.verify()
    return identity


class ReadOnlySession:
    def __init__(self, identity):
        if (identity.get('library_sha256') != CONTRACT['library_sha256']
                or identity.get('jni_exports') != CONTRACT['jni_exports']
                or identity.get('processing_location') != 'android'):
            raise ValueError('invalid audited resource identity')
        self.identity = identity
        self.pid = identity['pid']
        if type(self.pid) is not int or not 0 < self.pid < 1 << 22:
            raise ValueError('invalid game PID')
        self.base = int(identity['base'], 0)
        self.end = int(identity['executable_end'], 0)
        if self.base <= 0 or self.base % 4096 or self.end-self.base != CONTRACT['executable_span']:
            raise ValueError('invalid executable extent')
        self.proc = Path('/proc')/str(self.pid)
        self.used = 0
        maps = self.verify()
        self.mappings = []
        for low,high,mode,offset,path,line in parse_maps(maps):
            self.mappings.append((low, high, mode))
        if self.read(self.base, 4) != b'\x7fELF':
            raise ValueError('native ELF header differs')
        for pin in CONTRACT['jni_exports']:
            if hashlib.sha256(self.read(self.base+int(pin['va'], 0), pin['size'])).hexdigest() != pin['sha256']:
                raise ValueError('native JNI code differs')

    def verify(self):
        if start_time((self.proc/'stat').read_text()) != self.identity['process_start_time']:
            raise ValueError('game generation changed; never migrate a native handle')
        if (self.proc/'cmdline').read_bytes().split(b'\0')[0] != CONTRACT['package'].encode():
            raise ValueError('game process identity changed')
        maps = read_snapshot(self.proc/'maps')
        if self.identity['mapping'] not in maps.splitlines():
            raise ValueError('game mapping changed')
        if start_time((self.proc/'stat').read_text()) != self.identity['process_start_time']:
            raise ValueError('game changed during verification')
        return maps

    def read(self, address, size):
        address = checked_range(address, size, self.mappings, self.used)
        self.used += size
        self.verify()
        fd = os.open(self.proc/'mem', os.O_RDONLY | os.O_CLOEXEC)
        try:
            raw = os.pread(fd, size, address)
        finally:
            os.close(fd)
        if len(raw) != size:
            raise ValueError('short native resource read')
        self.verify()
        return raw

    def read_many(self, ranges):
        values = list(ranges)
        if len(values) > 4096:
            raise ValueError('too many resource ranges')
        used = self.used
        for address, size in values:
            checked_range(address, size, self.mappings, used)
            used += size
        self.verify()
        fd = os.open(self.proc/'mem', os.O_RDONLY | os.O_CLOEXEC)
        result = []
        try:
            for address, size in values:
                raw = os.pread(fd, size, address & MASK)
                if len(raw) != size:
                    raise ValueError('short native resource batch')
                result.append(raw)
        finally:
            os.close(fd)
        self.used = used
        self.verify()
        return result

    def pointer(self, address):
        return self.raw_pointer(address) & MASK

    def raw_pointer(self, address):
        # Android heap tags are part of a native object's identity. Strip them
        # only when addressing /proc/mem, never in bindings passed back to C++.
        return struct.unpack('<Q', self.read(address, 8))[0]
