"""Build a permission-free, separate ARM64 NativeActivity for real ART tests."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[1]
PACKAGE='org.codex.mumu.replayprobe'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--framework-res',type=Path,required=True);p.add_argument('--build-tools',type=Path,required=True)
    p.add_argument('--jdk',type=Path,required=True)
    p.add_argument('--resume-owned',action='store_true')
    args=p.parse_args();os.environ['ROYALE_REPLAY_CONFIG']=str(args.config.resolve())
    sys.path.insert(0,str(ROOT/'project/official-web-replay'))
    from portable_config import compiler_command,host_compiler_command
    from client_session import ensure_current_device_binding
    from mumu_runtime import validate_device
    adb=['adb','-s',ensure_current_device_binding()['serial']];validate_device(adb)
    existing=subprocess.run(adb+['shell','pm','path',PACKAGE],capture_output=True,text=True,timeout=10)
    out=args.output.resolve()
    if existing.returncode==0:
        previous=out/'MuMuReplayProbe.apk'
        if not args.resume_owned or not previous.is_file():raise RuntimeError('test package exists; explicit resume of its saved owned APK required')
        remote_apk=existing.stdout.strip().removeprefix('package:')
        observed=subprocess.check_output(adb+['shell','sha256sum',remote_apk],text=True,timeout=10).split()[0]
        if observed!=hashlib.sha256(previous.read_bytes()).hexdigest():raise RuntimeError('installed test package is not the saved owned APK')
    out.mkdir(parents=True,exist_ok=args.resume_owned)
    core=ROOT/'project/official-web-replay';tests=ROOT/'tests'
    run_id=uuid.uuid4().hex
    common=['-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-shared','-fPIC','-static-libstdc++','-DRR_ART_TEST_ID="'+run_id+'"']
    activity=out/'librr_mumu_art_test.so';host=out/'librr_mumu_art_host.so';guest=out/'librr_mumu_guest.so';component=out/'libmumu_fixture_component.so'
    subprocess.run(compiler_command()+common+[str(tests/'mumu_art_activity.cpp'),'-landroid','-llog','-o',str(activity)],check=True,timeout=45)
    subprocess.run(host_compiler_command()+common+['-I'+str(core),str(tests/'mumu_art_host.cpp'),'-ldl','-llog','-o',str(host)],check=True,timeout=45)
    subprocess.run(compiler_command()+common+['-DRR_MUMU_DYNAMIC_TEST',str(core/'mumu_bridge_guest.cpp'),str(tests/'mumu_bridge_fixture.cpp'),'-ldl','-o',str(guest)],check=True,timeout=45)
    subprocess.run(compiler_command()+common+[str(tests/'mumu_component_fixture.cpp'),'-o',str(component)],check=True,timeout=45)
    manifest=out/'AndroidManifest.xml'
    manifest.write_text('''<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="org.codex.mumu.replayprobe" android:versionCode="1" android:versionName="1">
<uses-sdk android:minSdkVersion="24" android:targetSdkVersion="28"/>
<application android:label="MuMu 回放适配测试" android:hasCode="false" android:debuggable="true" android:extractNativeLibs="true" android:allowBackup="false">
<activity android:name="android.app.NativeActivity" android:exported="true"><meta-data android:name="android.app.lib_name" android:value="rr_mumu_art_test"/>
<intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter></activity>
</application></manifest>''',encoding='utf-8')
    apk=out/'unsigned.apk'
    subprocess.run([str(args.build_tools/'aapt.exe'),'package','-f','-M',str(manifest),'-I',str(args.framework_res.resolve()),'-F',str(apk)],check=True,timeout=30)
    with zipfile.ZipFile(apk,'a',zipfile.ZIP_STORED) as z:z.write(activity,'lib/arm64-v8a/'+activity.name)
    aligned=out/'aligned.apk';signed=out/'MuMuReplayProbe.apk'
    subprocess.run([str(args.build_tools/'zipalign.exe'),'-f','-p','4',str(apk),str(aligned)],check=True,timeout=30)
    keystore=out/'probe.keystore'
    if not keystore.exists():subprocess.run([str(args.jdk/'bin/keytool.exe'),'-genkeypair','-keystore',str(keystore),'-storepass','android','-keypass','android','-alias','probe','-dname','CN=Local Replay Probe','-keyalg','RSA','-keysize','2048','-validity','3650'],check=True,capture_output=True,timeout=30)
    subprocess.run([str(args.jdk/'bin/java.exe'),'-jar',str(args.build_tools/'lib/apksigner.jar'),'sign','--ks',str(keystore),'--ks-pass','pass:android','--out',str(signed),str(aligned)],check=True,timeout=30)
    subprocess.run(adb+['install','--no-incremental']+(['-r'] if existing.returncode==0 else [])+[str(signed)],check=True,timeout=60)
    subprocess.run(adb+['shell','run-as',PACKAGE,'mkdir','-p','files'],check=True,timeout=10)
    remote='/data/local/tmp/royale_art_test_'+hashlib.sha256(host.read_bytes()+guest.read_bytes()).hexdigest()[:16]
    subprocess.run(adb+['shell','mkdir','-p',remote],check=True,timeout=10)
    for file in (host,guest,component):
        subprocess.run(adb+['push',str(file),remote+'/'+file.name],check=True,timeout=15)
        subprocess.run(adb+['shell','run-as',PACKAGE,'cp',remote+'/'+file.name,'files/'+file.name],check=True,timeout=15)
        observed=subprocess.check_output(adb+['shell','run-as',PACKAGE,'sha256sum','files/'+file.name],text=True,timeout=10).split()[0]
        if observed!=hashlib.sha256(file.read_bytes()).hexdigest():raise ValueError('test library transfer was not byte exact')
    subprocess.run(adb+['shell','am','start','-W','-n',PACKAGE+'/android.app.NativeActivity'],check=True,timeout=30)
    until=time.monotonic()+8
    result=None
    while time.monotonic()<until:
        got=subprocess.run(adb+['shell','run-as',PACKAGE,'cat','files/host-result.json'],capture_output=True,text=True,timeout=10)
        if got.returncode==0:
            result=json.loads(got.stdout)
            if result.get('stage')==4 and result.get('run_id')==run_id:
                activity_result=subprocess.run(adb+['shell','run-as',PACKAGE,'cat','files/activity-result.json'],capture_output=True,text=True,timeout=10)
                if activity_result.returncode==0:
                    activity_doc=json.loads(activity_result.stdout)
                    if activity_doc.get('host_library_loaded') and activity_doc.get('run_id')==run_id:break
        time.sleep(.25)
    for name in ('host-result.json','activity-result.json'):
        got=subprocess.run(adb+['shell','run-as',PACKAGE,'cat','files/'+name],capture_output=True,timeout=10)
        if got.returncode==0:(out/name).write_bytes(got.stdout)
    logs=subprocess.check_output(adb+['logcat','-d','-s','RR_MUMU_PROBE:V'],timeout=10)
    (out/'app.log').write_bytes(logs)
    exitinfo=subprocess.check_output(adb+['shell','dumpsys','activity','exit-info',PACKAGE],timeout=10)
    (out/'exit-info.log').write_bytes(exitinfo)
    live=subprocess.run(adb+['shell','pidof',PACKAGE],capture_output=True,text=True,timeout=10)
    summary=dict(run_id=run_id,host=result,activity=json.loads((out/'activity-result.json').read_text(encoding='utf-8')) if (out/'activity-result.json').exists() else None,
        process_alive=live.returncode==0,game_calls=False,game_integration_verified=False)
    summary['ok']=bool(result and result.get('ok') and result.get('run_id')==run_id and summary['activity']
        and summary['activity'].get('run_id')==run_id and summary['activity'].get('host_library_loaded') and summary['process_alive'])
    (out/'result.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False));print(logs.decode(errors='replace')[-2000:])
    if not summary['ok']:raise RuntimeError('real ART dynamic loading test did not pass; inspect retained files')


if __name__=='__main__':main()
