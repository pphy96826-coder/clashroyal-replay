from pathlib import Path
import hashlib,json,os,secrets,shutil,subprocess,zipfile,re
root=Path.cwd();source=root/'work/android-mumu-adaptation/source/android-adaptation';support=root/'work/android-mumu-support';out=root/'work/android-mumu-apk';out.mkdir(exist_ok=True)
stage=out/'stage';java_source=stage/'src';java_source.mkdir(parents=True,exist_ok=True)
tools=root/'work/package/WinReplay/tools';jdk=tools/'jdk17/bin';sdk=tools/'android-build-tools37';ndk=tools/'android-ndk-r27d/toolchains/llvm/prebuilt/windows-x86_64/bin';deps=support/'build-dependencies'
previous=json.loads((out/'build-report.json').read_text()) if (out/'build-report.json').exists() else {}
version=previous.get('version_code',2026102100)+1;revision=version-2026102100;name='2026.10.21-mumu-dev'+str(revision);package='local.royale.replay.mumu'
def run(args,env=None):subprocess.run(list(map(str,args)),check=True,env=env,timeout=180)
for file in (source/'app/src').rglob('*.java'):
    text=file.read_text(encoding='utf-8').replace('local.royale.replay.android',package).replace('com.microsoft.emmx','com.android.chrome').replace('Microsoft Edge','Google Chrome').replace('Edge','Chrome')
    if file.name=='NativePython.java':
        text=text.replace('StandaloneDoctor.root(command,90)','StandaloneDoctor.root(command,300)')
        marker='if(count<10)throw new IOException("incomplete runtime manifest");'
        assert text.count(marker)==1
        text=text.replace(marker,marker+'\n        for(String name:new String[]{"app/mumu-support/host/lldb-server","app/mumu-support/host/debug-child","app/mumu-support/compiler/bin/clang++","app/mumu-support/compiler/bin/ld.lld","app/mumu-support/runtime/bin/phone_runtime"}){File binary=member(root,name);if(binary.isFile()&&!binary.setExecutable(true,true))throw new IOException("cannot prepare verified MuMu host helper");}')
    if file.name=='MainActivity.java':
        old='button(root,"打开 RoyaleAPI 网页",new View.OnClickListener(){public void onClick(View v){startActivity(new Intent(MainActivity.this,BrowserActivity.class).putExtra("speed",ConsoleActions.speed()));}});'
        assert text.count(old)==1
        text=text.replace(old,'button(root,"打开 Chrome（RoyaleAPI）",new View.OnClickListener(){public void onClick(View v){try{startActivity(new Intent("android.intent.action.VIEW").setData(Uri.parse("https://royaleapi.com/")).setPackage("com.android.chrome"));}catch(Exception error){status.setText("无法打开 Chrome："+error.getMessage());}}});')
        text=text.replace('setTitle("安卓回放控制台")','setTitle("MuMu回放控制台")')
    target=java_source/file.relative_to(source/'app/src');target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text,encoding='utf-8')
manifest=(source/'app/AndroidManifest.xml').read_text(encoding='utf-8').replace('local.royale.replay.android',package).replace('安卓回放控制台','MuMu回放控制台 · 测试版')
manifest,n1=re.subn(r'android:versionCode="[0-9]+"','android:versionCode="'+str(version)+'"',manifest)
manifest,n2=re.subn(r'android:versionName="[^"]+"','android:versionName="'+name+'"',manifest)
assert n1==n2==1
manifest=manifest.replace('</queries>','<package android:name="com.android.chrome" /></queries>')
manifest=manifest.replace('</manifest>','<instrumentation android:name=".MuMuPlaybackIntegrationTests" android:targetPackage="'+package+'" android:label="Explicit MuMu end-to-end replay acceptance" /></manifest>')
(stage/'AndroidManifest.xml').write_text(manifest,encoding='utf-8')
native=stage/'native';native.mkdir(exist_ok=True)
with zipfile.ZipFile(root/'work/android-hotfix10/Android-Replay-20261020-hotfix10.apk') as original:
    for member in original.namelist():
        if member.startswith('lib/arm64-v8a/') and member.endswith('.so'):(native/Path(member).name).write_bytes(original.read(member))
for filename in ('python_bridge.cpp','phone_runtime.cpp'):
    text=(source/'native'/filename).read_text().replace('local.royale.replay.android',package).replace('Java_local_royale_replay_android_','Java_local_royale_replay_mumu_')
    if filename=='phone_runtime.cpp':text=text.replace('    return result?4:0;','    PyRun_SimpleString("import sys;sys.stdout.flush();sys.stderr.flush()");\n    return result?4:0;')
    cpp=stage/filename;cpp.write_text(text,encoding='utf-8')
    args=[ndk/'clang++.exe','--target=aarch64-linux-android24','-std=c++17','-O2','-Wall','-Wextra','-Werror','-static-libstdc++','-Wl,-z,defs','-I'+str(support/'prefix/include/python3.14'),cpp,'-L'+str(native),'-lpython3.14']
    args+=['-fPIC','-shared','-o',native/'libreplay_python.so'] if filename=='python_bridge.cpp' else ['-fPIE','-pie','-Wl,-rpath,$ORIGIN','-o',native/'libphone_runtime.so']
    run(args)
classes=out/('classes-'+str(version));classes.mkdir(exist_ok=False)
api=deps/'android-32.jar';webkit=deps/'webkit-1.9.0.jar'
args=out/'javac.args';args.write_text('\n'.join('"'+str(p).replace('\\','/')+'"' for p in java_source.rglob('*.java')),encoding='utf-8')
run([jdk/'javac.exe','-J-Xmx192m','-encoding','UTF-8','-source','8','-target','8','-classpath',str(api)+os.pathsep+str(webkit),'-d',classes,'@'+str(args)])
jar=out/'classes.jar'
with zipfile.ZipFile(jar,'w') as z:
    for file in classes.rglob('*.class'):z.write(file,file.relative_to(classes).as_posix())
dex=out/('dex-'+str(version));dex.mkdir(exist_ok=False)
run([jdk/'java.exe','-Xmx384m','-cp',sdk/'lib/d8.jar','com.android.tools.r8.D8','--min-api','26','--lib',api,'--output',dex,jar,webkit])
cache=root/'work/android-mumu-build-cache';cache.mkdir(exist_ok=True)
unsigned=cache/'unsigned.apk';run([sdk/'aapt2.exe','link','-o',unsigned,'--manifest',stage/'AndroidManifest.xml','-I',api])
bundle=support/'mumu-development-python.zip';meta=json.loads((support/'development-bundle.json').read_text());assert hashlib.sha256(bundle.read_bytes()).hexdigest()==meta['sha256']
with zipfile.ZipFile(unsigned,'a') as apk,zipfile.ZipFile(root/'work/android-hotfix10/Android-Replay-20261020-hotfix10.apk') as original:
    for member in original.namelist():
        if not member.startswith('assets/') or member in ('assets/python-runtime.zip','assets/python-runtime.sha256'):continue
        with original.open(member) as src,apk.open(member,'w') as dest:shutil.copyfileobj(src,dest)
    apk.write(bundle,'assets/python-runtime.zip',compress_type=zipfile.ZIP_STORED)
    apk.writestr('assets/python-runtime.sha256',meta['sha256'])
    for file in dex.glob('classes*.dex'):apk.write(file,file.name,compress_type=zipfile.ZIP_STORED)
    for file in native.glob('*.so'):apk.write(file,'lib/arm64-v8a/'+file.name,compress_type=zipfile.ZIP_DEFLATED)
aligned=cache/'aligned.apk';run([sdk/'zipalign.exe','-f','4',unsigned,aligned])
private=out/'private';private.mkdir(exist_ok=True);password=private/'password.txt';key=private/'mumu-development.jks'
if not password.exists():password.write_text(secrets.token_hex(24),encoding='ascii')
environment=dict(os.environ,RR_MUMU_SIGNING_PASSWORD=password.read_text(encoding='ascii'))
if not key.exists():run([jdk/'keytool.exe','-J-Xmx64m','-genkeypair','-keystore',key,'-alias','mumu-replay','-keyalg','RSA','-keysize','2048','-validity','3650','-dname','CN=MuMu Replay Development','-storepass:env','RR_MUMU_SIGNING_PASSWORD','-keypass:env','RR_MUMU_SIGNING_PASSWORD'],environment)
apk=out/('MuMu-Replay-20261021-dev'+str(revision)+'.apk')
run([jdk/'java.exe','-Xmx128m','-jar',sdk/'lib/apksigner.jar','sign','--ks',key,'--ks-key-alias','mumu-replay','--ks-pass','env:RR_MUMU_SIGNING_PASSWORD','--out',apk,aligned],environment)
run([jdk/'java.exe','-Xmx128m','-jar',sdk/'lib/apksigner.jar','verify','--verbose',apk])
report=dict(package=package,version=name,version_code=version,sha256=hashlib.sha256(apk.read_bytes()).hexdigest(),bytes=apk.stat().st_size,signature_verified=True,official_sdk_api=32,python_bundle_sha256=meta['sha256'],device_e2e_verified=False,original_app_preserved=True)
(out/'build-report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
deliver=root/('outputs/Android原生复现/MuMu回放控制台-20261021-dev'+str(revision)+'.apk')
try:os.link(apk,deliver)
except OSError:shutil.copyfile(apk,deliver)
