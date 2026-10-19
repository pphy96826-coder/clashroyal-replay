"""Package this experimental Windows source fork without personal/runtime data."""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def main():
    output=ROOT.parent/'releases/windows-replay-preview-20261016.zip'
    if output.exists():raise FileExistsError('versioned preview already exists')
    skip={'__pycache__','console-runs','runtime','build-readonly-memory'};files=[]
    for file in sorted(ROOT.rglob('*')):
        if not file.is_file() or any(part in skip for part in file.relative_to(ROOT).parts):continue
        if file.suffix in ('.pyc','.so','.exe','.apk','.aiff','.wav','.log'):raise ValueError('runtime material in source release: '+str(file))
        if file.suffix=='.py':ast.parse(file.read_text(encoding='utf-8'))
        if re.search(rb'/Users/'+rb'[\w.-]+/',file.read_bytes()):raise ValueError('personal home directory leaked')
        files.append(file)
    hashes={file.relative_to(ROOT).as_posix():hashlib.sha256(file.read_bytes()).hexdigest() for file in files}
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for file in files:archive.write(file,'windows-adaptation/'+file.relative_to(ROOT).as_posix())
        archive.writestr('windows-adaptation/release-manifest.json',json.dumps(hashes,indent=2)+'\n')
    with tempfile.TemporaryDirectory(prefix='windows release 解压 ') as folder:
        with zipfile.ZipFile(output) as archive:
            if archive.testzip() is not None:raise ValueError('archive CRC mismatch')
            archive.extractall(folder)
        extracted=Path(folder)/'windows-adaptation'
        for relative,expected in hashes.items():
            if hashlib.sha256((extracted/relative).read_bytes()).hexdigest()!=expected:raise ValueError('extracted hash mismatch')
        subprocess.run([sys.executable,'-X','utf8','-m','unittest','discover','-s',str(extracted/'tests')],check=True,timeout=30)
    report=dict(archive=str(output),files=len(files),bytes=output.stat().st_size,sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
        native_windows_tested=False,windows_vm_available=False,device_contacted=False)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
