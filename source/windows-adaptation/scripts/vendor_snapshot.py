"""Copy only manifest-verified portable sources into a new Windows fork."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source-skill',type=Path,required=True);args=parser.parse_args()
    source=args.source_skill.resolve();payload=source/'assets/project';target=ROOT/'project'
    expected=json.loads((source/'assets/payload-manifest.json').read_text(encoding='utf-8'))['files']
    actual={p.relative_to(payload).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in payload.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    if actual!=expected:raise ValueError('source Skill manifest mismatch')
    if target.exists():raise FileExistsError('snapshot already exists; do not overwrite Windows edits')
    count=0
    for relative in expected:
        if relative.endswith('.swift'):continue
        out=target/relative;out.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(payload/relative,out);count+=1
    # Make every text artifact independent of the Windows ANSI code page.
    for path in target.rglob('*.py'):
        text=path.read_text(encoding='utf-8').replace('read_text()','read_text(encoding="utf-8")')
        for mode in ('x','w','a','r'):
            text=text.replace(".open('"+mode+"')",".open('"+mode+"',encoding='utf-8')")
        text=text.replace("os.fdopen(fd, 'w')","os.fdopen(fd, 'w', encoding='utf-8')")
        path.write_text(text,encoding='utf-8')
    (ROOT/'upstream-manifest.json').write_text(json.dumps(expected,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(copied_source_files=count,mac_source_modified=False)))


if __name__=='__main__':main()
