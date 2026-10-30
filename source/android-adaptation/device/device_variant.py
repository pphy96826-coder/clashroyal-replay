"""Choose an embedded audited adapter by the freshly installed full library hash.

No downloaded adapters, inherited process handles or version-string approvals.
The base app contains the previous audited adapter; newer adapters are isolated
siblings so selecting one never rewrites the other's Python or native sources.
"""
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile


def installed_apk(action, source, extra):
    if action in ('check-tools', 'check-native-tools', 'import-source', 'reset', 'release-preparation'):
        return None
    if action == 'prepare':
        return extra
    if action == 'play':
        return Path(json.loads(source.read_text())['apk'])
    if action == 'build-component':
        observation = source.parent/'runtime/runtime-observation.json'
        return Path(json.loads(observation.read_text())['identity']['apk'])
    if action in ('recover', 'finish'):
        return Path(json.loads(source.read_text())['identity']['apk'])
    raise ValueError('Unknown fixed replay action')


def library_hash(apk):
    if not re.fullmatch(r'/data/app/[A-Za-z0-9_=./+~\-]+/base\.apk', str(apk)):
        raise ValueError('Not an installed game APK')
    with zipfile.ZipFile(apk) as archive:
        info = archive.getinfo('lib/arm64-v8a/libg.so')
        if not 64 <= info.file_size <= 128*1024*1024:
            raise ValueError('Invalid bounded native library')
        digest = hashlib.sha256(); total = 0
        with archive.open(info) as stream:
            for block in iter(lambda: stream.read(1024*1024), b''):
                total += len(block)
                if total > info.file_size:
                    raise ValueError('Native library exceeds declared size')
                digest.update(block)
        if total != info.file_size:
            raise ValueError('Incomplete native library')
        return digest.hexdigest()


def adapter_path(home, digest):
    if not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('Full native hash required')
    base = home/'app'
    original = json.loads((base/'native-contract.json').read_text())
    if original['library_sha256'] == digest:
        return base
    variant = home/'variants'/digest/'app'
    contract = json.loads((variant/'native-contract.json').read_text()) if variant.is_dir() else {}
    if (contract.get('library_sha256') != digest or contract.get('supported') is not True
            or contract.get('native_execution_allowed') is not True):
        raise ValueError('Installed client has no verified embedded adapter')
    return variant


def select(home, action, source, extra):
    apk = installed_apk(action, source, extra)
    if apk is None:
        return home/'app'
    selected = adapter_path(home, library_hash(apk))
    # Called before importing any resource/debugger/native adapter module.
    sys.path.insert(0, str(selected))
    return selected
