"""Build/sign own companion APK offline. Never patches/re-signs the game APK."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import zipfile
from compile_api import API

ROOT=Path(__file__).resolve().parents[1]

def run(command,env=None):subprocess.run(list(map(str,command)),check=True,env=env,timeout=120)

def main():
    p=argparse.ArgumentParser();p.add_argument('--jdk',type=Path,required=True);p.add_argument('--build-tools',type=Path,required=True)
    p.add_argument('--android-jar',type=Path);p.add_argument('--framework-res',type=Path);p.add_argument('--embedded-python',action='store_true');p.add_argument('--android-tools',action='store_true');a=p.parse_args()
    if a.android_tools and not a.embedded_python:raise ValueError('Android tools self-check requires embedded Python')
    os.umask(0o077);out=ROOT/'build';out.mkdir(exist_ok=True)
    for tool in ('java','javac','jar','keytool'):
        if not (a.jdk/'bin'/tool).is_file():raise FileNotFoundError(tool)
    java=a.jdk/'bin/java';javac=a.jdk/'bin/javac'
    api=a.android_jar
    if api is None:
        directory=out/'api-src';classes=out/'api-classes';directory.mkdir(exist_ok=True);classes.mkdir(exist_ok=True);files=[]
        for name,source in API.items():
            package,cls=name.rsplit('.',1);path=directory/Path(*package.split('.'))/(cls+'.java');path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text('package '+package+';\n'+source+'\n',encoding='utf-8');files.append(path)
        run([javac,'-encoding','UTF-8','-source','8','-target','8','-d',classes,*files])
        api=out/'compile-only-api.jar';run([a.jdk/'bin/jar','cf',api,'-C',classes,'.'])
    resources=a.android_jar or a.framework_res
    if not resources or not resources.is_file():raise ValueError('official SDK android.jar or own device framework resources required')
    classes=out/'classes';classes.mkdir(exist_ok=True)
    # Fresh generated class directories prevent removed UI handlers lingering in dex.
    for stale in classes.rglob('*.class'):stale.unlink()
    webkit=ROOT/'toolchain/webkit/webkit-1.9.0.jar'
    if not webkit.is_file():raise FileNotFoundError('Pinned AndroidX WebKit jar required; do not download or fall back here')
    lock=json.loads((ROOT/'scripts/webkit.lock.json').read_text())
    if hashlib.sha256(webkit.read_bytes()).hexdigest()!=lock['classes_sha256']:raise ValueError('AndroidX WebKit jar differs')
    source=list((ROOT/'app/src').rglob('*.java'))
    run([javac,'-encoding','UTF-8','-source','8','-target','8','-classpath',str(api)+os.pathsep+str(webkit),'-d',classes,*source])
    dex=out/'dex';dex.mkdir(exist_ok=True)
    run([java,'-cp',a.build_tools/'lib/d8.jar','com.android.tools.r8.D8','--min-api','26','--lib',a.jdk,'--lib',api,'--output',dex,webkit,*classes.rglob('*.class')])
    unsigned=out/'unsigned.apk'
    run([a.build_tools/'aapt2','link','-o',unsigned,'--manifest',ROOT/'app/AndroidManifest.xml','-I',resources,'-A',ROOT/'app/assets'])
    with zipfile.ZipFile(unsigned,'a') as archive:
        for file in dex.glob('classes*.dex'):archive.write(file,file.name,compress_type=zipfile.ZIP_STORED)
        if a.embedded_python:
            for name in ('python-runtime.zip','python-runtime.sha256'):
                archive.write(out/'python-bundle'/name,'assets/'+name,compress_type=zipfile.ZIP_STORED)
            for file in sorted((out/'embedded-native').glob('*.so')):archive.write(file,'lib/arm64-v8a/'+file.name,compress_type=zipfile.ZIP_DEFLATED)
        if a.android_tools:
            for name in ('android-tools.zip','android-tools.sha256'):
                archive.write(out/'android-tools-bundle'/name,'assets/'+name,compress_type=zipfile.ZIP_STORED)
    aligned=out/'aligned.apk';run([a.build_tools/'zipalign','-f','4',unsigned,aligned])
    private=ROOT/'private';private.mkdir(exist_ok=True,mode=0o700);key=private/'local-debug.jks';password=private/'signing-password.txt'
    if not password.exists():password.write_text(secrets.token_hex(24),encoding='utf-8')
    env=dict(os.environ,RR_SIGNING_PASSWORD=password.read_text(encoding='utf-8'))
    if not key.exists():run([a.jdk/'bin/keytool','-genkeypair','-keystore',key,'-alias','replay-console','-keyalg','RSA','-keysize','2048',
        '-validity','3650','-dname','CN=Local Replay Development','-storepass:env','RR_SIGNING_PASSWORD','-keypass:env','RR_SIGNING_PASSWORD'],env)
    apk=out/'royale-replay-android-debug.apk'
    run([java,'-jar',a.build_tools/'lib/apksigner.jar','sign','--ks',key,'--ks-key-alias','replay-console','--ks-pass','env:RR_SIGNING_PASSWORD','--out',apk,aligned],env)
    run([java,'-jar',a.build_tools/'lib/apksigner.jar','verify','--verbose',apk])
    with zipfile.ZipFile(apk) as archive:
        if any(n.startswith(('android/','org/json/')) for n in archive.namelist()):raise ValueError('compile-only API leaked into APK')
    report=dict(apk=str(apk),sha256=hashlib.sha256(apk.read_bytes()).hexdigest(),bytes=apk.stat().st_size,
        official_sdk_used=a.android_jar is not None,compile_only_api_fallback=a.android_jar is None,
        device_resources_used=a.framework_res is not None,signature_verified=True,independent_phone_runtime=False,
        network_permission=True,webview_route='app-local-direct',system_network_changed=False,webkit_version='1.9.0',device_tested=False,embedded_python=a.embedded_python,android_tools_experiment=a.android_tools)
    (out/'build-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
