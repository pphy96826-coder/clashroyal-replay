"""Inspect relocatable Android debugger dependencies in a private build area.

Download only through the user's existing proxy. Do not run package installers,
postinst scripts, or write Termux/system/app-private paths on the device.
This is a toolchain compatibility experiment, not a standalone release.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import posixpath
import shutil
import subprocess
import tarfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
BASE='https://packages.termux.dev/apt/termux-main/'
PREFIX=PurePosixPath('data/data/com.termux/files/usr')
NAMES=('lldb','clang','lld','ndk-sysroot','libcompiler-rt','libllvm','libc++','libffi','libxml2','libandroid-glob','libiconv',
       'ncurses','ncurses-ui-libs','libedit','libandroid-spawn','zlib','zstd','liblzma')


def packages(raw):
    result={}
    for block in gzip.decompress(raw).decode().split('\n\n'):
        fields={line.split(': ',1)[0]:line.split(': ',1)[1] for line in block.splitlines() if ': ' in line and not line.startswith(' ')}
        if fields.get('Package') not in NAMES:continue
        name=fields['Package']
        if name in result or fields['Architecture']!='aarch64' or not re.fullmatch('[a-f0-9]{64}',fields['SHA256']):raise ValueError('ambiguous package identity')
        path=PurePosixPath(fields['Filename'])
        if path.is_absolute() or '..' in path.parts or not fields['Filename'].startswith('pool/main/'):raise ValueError('unsafe repository path')
        result[name]=fields
    if set(result)!=set(NAMES):raise ValueError('incomplete official toolchain index')
    return result


def ar_data(raw):
    if raw[:8]!=b'!<arch>\n':raise ValueError('invalid Debian archive')
    offset=8;data=[]
    while offset<len(raw):
        header=raw[offset:offset+60]
        if len(header)!=60 or header[58:]!=b'`\n':raise ValueError('invalid ar header')
        size=int(header[48:58]);name=header[:16].decode().strip().rstrip('/')
        start=offset+60
        if size<0 or start+size>len(raw):raise ValueError('short ar member')
        if name.startswith('data.tar.'):data.append(raw[start:start+size])
        offset=start+size+(size%2)
    if len(data)!=1:raise ValueError('one data archive required')
    return data[0]


def extract(raw,root,package):
    files=0;total=0
    with tarfile.open(fileobj=io.BytesIO(ar_data(raw)),mode='r:*') as archive:
        for item in archive:
            path=PurePosixPath(item.name)
            if path.is_absolute() or '..' in path.parts:raise ValueError('unsafe package member')
            if path==PREFIX or PREFIX not in path.parents:continue
            relative=path.relative_to(PREFIX)
            # Android headers can differ only by case (xt_CONNMARK.h versus
            # xt_connmark.h). Preserve them directly in the ZIP below instead
            # of flattening them onto a case-insensitive host filesystem.
            if relative.parts[0]=='include':continue
            # Manuals contain case-distinct aliases on Android that collide on
            # a default case-insensitive macOS volume. They are not runtime or
            # licence inputs; the verified original .deb stays in the cache.
            if relative.parts[:2]==('share','man'):continue
            # Debian alternatives can intentionally overlap compressed man
            # pages. Preserve each package's docs/licences, not an arbitrary
            # winning file. Runtime files may never conflict.
            if relative.parts[:2] in (('share','man'),('share','doc')):
                relative=PurePosixPath('share/package-docs')/package/PurePosixPath(*relative.parts[1:])
            target=root.joinpath(*relative.parts)
            if item.isdir():target.mkdir(parents=True,exist_ok=True);continue
            if item.issym():
                link=PurePosixPath(item.linkname)
                if link.is_absolute():
                    link=link.relative_to('/'+str(PREFIX))
                    import os
                    link=PurePosixPath(os.path.relpath(root.joinpath(*link.parts),target.parent))
                if not (target.parent/str(link)).resolve().is_relative_to(root.resolve()):raise ValueError('package symlink escapes private tools')
                target.parent.mkdir(parents=True,exist_ok=True)
                if target.is_symlink() and target.readlink()==Path(str(link)):continue
                if target.exists() or target.is_symlink():raise ValueError('conflicting package link')
                target.symlink_to(str(link));continue
            if not item.isfile():raise ValueError('unsupported package member')
            total+=item.size;files+=1
            if files>40000 or total>512*1024*1024:raise ValueError('tool archive budget exceeded')
            if not target.resolve().is_relative_to(root.resolve()):raise ValueError('file escapes private tools')
            target.parent.mkdir(parents=True,exist_ok=True)
            with archive.extractfile(item) as source:
                content=source.read()
            if target.exists():
                if not target.is_file() or target.read_bytes()!=content:raise ValueError('conflicting package file: '+str(relative))
            else:
                with target.open('xb') as output:output.write(content)
                target.chmod(0o700 if item.mode&0o111 else 0o600)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--index',type=Path,required=True)
    parser.add_argument('--ndk-prefix',type=Path,required=True,help='existing NDK toolchains/llvm/prebuilt/<host>, for matching static C++ runtime')
    parser.add_argument('--download',action='store_true');args=parser.parse_args()
    index=args.index.read_bytes();rows=packages(index)
    cache=ROOT/'toolchain/android-packages';cache.mkdir(exist_ok=True)
    lock={name:{key:row[key] for key in ('Version','Filename','Size','SHA256')} for name,row in rows.items()}
    encoded=json.dumps(dict(packages=lock,layout_schema=2),sort_keys=True).encode();digest=hashlib.sha256(encoded).hexdigest()
    area=ROOT/'toolchain'/('debugger-'+digest[:16]);area.mkdir(exist_ok=True)
    def fetch(name):
        row=rows[name];file=cache/Path(row['Filename']).name
        if not file.exists():
            if not args.download:raise FileNotFoundError(file)
            part=file.with_suffix(file.suffix+'.part')
            subprocess.run(['curl','--fail','--location','--proto','=https','--retry','2','--retry-all-errors',
                '--connect-timeout','15','--max-time','150','--proxy','http://127.0.0.1:7890','--noproxy','',
                '--silent','--show-error','--output',str(part),BASE+row['Filename']],check=True)
            if part.stat().st_size!=int(row['Size']) or hashlib.sha256(part.read_bytes()).hexdigest()!=row['SHA256']:raise ValueError('downloaded package hash differs')
            part.rename(file)
        raw=file.read_bytes()
        if len(raw)!=int(row['Size']) or hashlib.sha256(raw).hexdigest()!=row['SHA256']:raise ValueError('cached package hash differs')
        print(name+': SHA256 verified',flush=True)
        return raw
    with ThreadPoolExecutor(max_workers=2) as pool:archives=list(pool.map(fetch,NAMES))
    usr=area/'usr';usr.mkdir(exist_ok=True)
    for name,raw in zip(NAMES,archives):extract(raw,usr,name)
    report=dict(schema='royale-replay.android-debugger-experiment.v1',index_sha256=hashlib.sha256(index).hexdigest(),
                packages=lock,toolchain_sha256=digest,private_tools=str(usr),
                package_installers_run=False,postinst_run=False,device_installed=False,relocation_verified=False)
    (area/'manifest.json').write_text(json.dumps(report,indent=2))
    bundle=ROOT/'build/android-tools-bundle';bundle.mkdir(exist_ok=True)
    package=bundle/'android-tools.zip';members={};headers={};header_links={}
    for raw in archives:
        with tarfile.open(fileobj=io.BytesIO(ar_data(raw)),mode='r:*') as archive:
            for item in archive:
                path=PurePosixPath(item.name)
                if path.is_absolute() or '..' in path.parts:raise ValueError('unsafe header archive path')
                if PREFIX not in path.parents:continue
                relative=path.relative_to(PREFIX)
                if relative.parts[0]!='include' or item.isdir():continue
                if item.issym() or item.islnk():
                    link=PurePosixPath(item.linkname)
                    if link.is_absolute():link=link.relative_to('/'+str(PREFIX))
                    elif item.islnk() and PREFIX in link.parents:link=link.relative_to(PREFIX)
                    else:link=relative.parent/link
                    target=posixpath.normpath(link.as_posix())
                    if not target.startswith('include/'):raise ValueError('header alias leaves include tree')
                    header_links[relative.as_posix()]=target
                    continue
                if not item.isfile():raise ValueError('unsupported nonregular compiler header: '+str(relative))
                with archive.extractfile(item) as stream:content=stream.read()
                name=relative.as_posix()
                if name in headers and headers[name]!=content:raise ValueError('conflicting compiler header: '+name)
                headers[name]=content
    while header_links:
        ready=[name for name,target in header_links.items() if target in headers]
        if not ready:raise ValueError('unresolved compiler header aliases: '+repr(header_links))
        for name in ready:headers[name]=headers[header_links.pop(name)]
    for file in sorted(usr.rglob('*')):
        relative=file.relative_to(usr)
        if not file.is_file() or 'man' in relative.parts or relative.parts[0]=='include':continue
        # This is a private project toolchain, not a Termux installation.
        # Avoid duplicating the 134MB LLVM alias and 17MB Python
        # binding alias; device_tools loads the same liblldb ELF explicitly.
        if relative.as_posix() in ('lib/libLLVM-21.so','lib/python3.14/site-packages/lldb/_lldb.cpython-314.so'):continue
        if relative.parts[0] not in ('lib','share','include','bin'):continue
        if relative.parts[0]=='bin' and relative.name not in ('clang','clang++','ld.lld','lldb-server'):continue
        if not file.resolve().is_relative_to(usr.resolve()):raise ValueError('tool link escapes private prefix')
        members[relative.as_posix()]=file
    for name in ('libc++_static.a','libc++abi.a'):
        file=args.ndk_prefix/'sysroot/usr/lib/aarch64-linux-android'/name
        if not file.is_file():raise FileNotFoundError('existing audited-project NDK static runtime missing: '+name)
        members['lib/'+name]=file
    for name,file in (('ndk-NOTICE',args.ndk_prefix.parents[3]/'NOTICE'),
                      ('ndk-toolchain-NOTICE',args.ndk_prefix/'NOTICE'),
                      ('ndk-sysroot-NOTICE',args.ndk_prefix/'sysroot/NOTICE')):
        if not file.is_file():raise FileNotFoundError('existing NDK notice missing')
        members['share/'+name]=file
    with zipfile.ZipFile(package,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name,file in members.items():archive.write(file,name)
        for name,content in headers.items():archive.writestr(name,content)
        manifest={name:hashlib.sha256(file.read_bytes()).hexdigest() for name,file in members.items()}
        manifest.update({name:hashlib.sha256(content).hexdigest() for name,content in headers.items()})
        archive.writestr('runtime-files.json',json.dumps(manifest,sort_keys=True))
        archive.writestr('toolchain-sources.json',json.dumps({k:v for k,v in report.items() if k!='private_tools'},sort_keys=True))
    (bundle/'android-tools.sha256').write_text(hashlib.sha256(package.read_bytes()).hexdigest())
    print(json.dumps({k:v for k,v in report.items() if k!='packages'},indent=2))


if __name__=='__main__':main()
