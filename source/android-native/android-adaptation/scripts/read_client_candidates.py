"""Capture bounded candidate CODE through an existing root ADB connection.

Only the configured selected loopback device is used. No attach, game calls,
memory writes, permission changes, emulator restart or client modification.
Input candidates remain hypotheses even when the loaded bytes are stable.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import struct
import subprocess
import zipfile

PACKAGE = 'com.tencent.tmgp.supercell.clashroyale'
LIBRARY = 'lib/arm64-v8a/libg.so'


def sha_file(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def start_time(data):
    fields = data.rsplit(b')', 1)[-1].split()
    if len(fields) <= 19 or not fields[19].isdigit():
        raise ValueError('invalid game process generation')
    return fields[19].decode('ascii')


def validate_candidates(doc):
    if (doc.get('schema') != 'royale-replay.code-candidates.v1'
            or not re.fullmatch('[0-9a-f]{64}', doc.get('library_sha256', ''))):
        raise ValueError('candidate manifest identity required')
    rows = doc['functions']
    if not isinstance(rows, dict) or not 1 <= len(rows) <= 256:
        raise ValueError('bounded named candidate set required')
    total = 0
    for name, row in rows.items():
        if not re.fullmatch('[a-z][a-z0-9_-]{0,63}', name):
            raise ValueError('invalid candidate name')
        va = int(row['va'], 0)
        size = row['bytes']
        if type(size) is not int or not 0 < size <= 4096 or size % 4 or va <= 0 or va % 4:
            raise ValueError('invalid aligned code range')
        total += 2 * size  # Stability verification reads every byte twice.
    if total > 65536:
        raise ValueError('64KiB capture budget exceeded')
    return total


class Snapshot:
    def __init__(self, config, local_apk, expected_hash):
        settings = json.loads(Path(config['vm_settings']).expanduser().read_text())
        port = settings['adbPort']
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError('configured loopback ADB port required')
        self.adb = [config['adb'], '-s', '127.0.0.1:' + str(port)]
        if self.shell('id', '-u').strip() != b'0':
            raise PermissionError('existing root ADB access required; no permission changes')
        self.pid = self.shell('pidof', PACKAGE).decode().strip()
        if not re.fullmatch('[1-9][0-9]{0,6}', self.pid):
            raise ValueError('exactly one running game process required')
        self.proc = '/proc/' + self.pid
        self.start = start_time(self.shell('cat', self.proc + '/stat'))
        lines = self.shell('pm', 'path', PACKAGE).decode().splitlines()
        if len(lines) != 1 or not lines[0].startswith('package:'):
            raise ValueError('single installed base APK required')
        self.apk = lines[0][8:]
        if not re.fullmatch(r'/data/app/[A-Za-z0-9_=./+~\-]+/base\.apk', self.apk):
            raise ValueError('unexpected installed APK path')
        # Authenticate the user's local APK against the actual selected device,
        # rather than trusting an earlier package name or file copy.
        local_hash = sha_file(local_apk)
        remote_hash = self.shell('sha256sum', self.apk).decode().split()[0]
        if local_hash != remote_hash:
            raise ValueError('installed APK changed; refresh local private copy')
        self.apk_sha256 = local_hash
        with zipfile.ZipFile(local_apk) as archive:
            entry = archive.getinfo(LIBRARY)
            if entry.compress_type != zipfile.ZIP_STORED or not 64 <= entry.file_size <= 128*1024*1024:
                raise ValueError('bounded stored ARM64 library required')
            with archive.open(entry) as stream:
                h = hashlib.sha256()
                count = 0
                for block in iter(lambda: stream.read(1024*1024), b''):
                    count += len(block)
                    if count > entry.file_size:
                        raise ValueError('library exceeds declared size')
                    h.update(block)
            if count != entry.file_size or h.hexdigest() != expected_hash:
                raise ValueError('candidate library hash differs')
        self.library_sha256 = expected_hash
        with local_apk.open('rb') as stream:
            stream.seek(entry.header_offset)
            header = stream.read(30)
        if header[:4] != b'PK\x03\x04':
            raise ValueError('invalid APK local header')
        names, extra = struct.unpack_from('<HH', header, 26)
        self.offset = entry.header_offset + 30 + names + extra
        if self.offset % 4096:
            raise ValueError('library mapping is not page aligned')
        rows = self.mapping_rows()
        if len(rows) != 1:
            raise ValueError('library executable mapping absent or ambiguous')
        self.mapping = rows[0]
        extent = self.mapping.split()[0].split('-')
        self.base, self.end = (int(v, 16) for v in extent)
        self.used = 0
        self.verify()

    def shell(self, *args):
        command = shlex.join(args)
        return subprocess.run([*self.adb, 'shell', command], check=True,
                              capture_output=True, timeout=30).stdout

    def mapping_rows(self):
        rows = []
        for line in self.shell('cat', self.proc + '/maps').decode().splitlines():
            parts = line.split()
            if (len(parts) == 6 and parts[1] == 'r-xp' and parts[5] == self.apk
                    and int(parts[2], 16) == self.offset):
                rows.append(line)
        return rows

    def verify(self):
        if start_time(self.shell('cat', self.proc + '/stat')) != self.start:
            raise ValueError('game generation changed; discard this snapshot')
        if self.shell('cat', self.proc + '/cmdline').split(b'\0')[0] != PACKAGE.encode():
            raise ValueError('game process identity changed')
        if b'TracerPid:\t0' not in self.shell('cat', self.proc + '/status').splitlines():
            raise ValueError('another debugger owns the game')
        if self.mapping_rows() != [self.mapping]:
            raise ValueError('game executable mapping changed')
        if start_time(self.shell('cat', self.proc + '/stat')) != self.start:
            raise ValueError('game generation changed during verification')

    def read(self, va, size):
        address = self.base + va
        if (type(size) is not int or not 0 < size <= 4096 or size % 4
                or va <= 0 or va % 4 or not self.base <= address < address + size <= self.end
                or self.used + 2*size > 65536):
            raise ValueError('candidate code range or read budget exceeded')
        self.verify()
        command = (f'dd if={self.proc}/mem bs=4 skip={address//4} '
                   f'count={size//4} 2>/dev/null')
        def once():
            self.used += size
            raw = subprocess.run([*self.adb, 'exec-out', command], check=True,
                                 capture_output=True, timeout=10).stdout
            if len(raw) != size:
                raise ValueError('short executable code read')
            self.verify()
            return raw
        first = once()
        if first != once():
            raise ValueError('loaded code changed during observation')
        return first


def capture(config, apk, candidates, destination):
    validate_candidates(candidates)
    session = Snapshot(config, apk, candidates['library_sha256'])
    destination.mkdir(mode=0o700, exist_ok=False)
    rows = {}
    for name, row in candidates['functions'].items():
        raw = session.read(int(row['va'], 0), row['bytes'])
        name_on_disk = name + '.bin'
        with open(destination/name_on_disk, 'xb', opener=lambda p, f: os.open(p, f, 0o600)) as stream:
            stream.write(raw)
        rows[name] = dict(file=name_on_disk, va=row['va'], bytes=len(raw),
                          sha256=hashlib.sha256(raw).hexdigest())
    session.verify()
    report = dict(schema='royale-replay.loaded-code-snapshot.v1',
                  library_sha256=session.library_sha256, apk_sha256=session.apk_sha256,
                  process_id=int(session.pid), process_start_time=session.start,
                  functions=rows, generation_verified=True, read_bytes=session.used,
                  native_calls=False, game_memory_written=False, candidate_only=True)
    with open(destination/'snapshot.json', 'x', opener=lambda p, f: os.open(p, f, 0o600)) as stream:
        json.dump(report, stream, indent=2)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--apk', type=Path, required=True)
    parser.add_argument('--candidates', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = capture(json.loads(args.config.read_text()), args.apk,
                     json.loads(args.candidates.read_text()), args.output)
    print(json.dumps({key: result[key] for key in (
        'library_sha256', 'read_bytes', 'generation_verified', 'native_calls', 'game_memory_written')}))


if __name__ == '__main__':
    main()
