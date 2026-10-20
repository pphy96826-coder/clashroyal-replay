"""Offline source installer/doctor. Does not start an emulator or a battle."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys
import venv
import uuid

SKILL=Path(__file__).resolve().parents[1]
PAYLOAD=SKILL/'assets/project'


def verify_package():
    expected=json.loads((SKILL/'assets/payload-manifest.json').read_text())['files']
    actual={p.relative_to(PAYLOAD).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in PAYLOAD.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    if actual!=expected:
        raise ValueError('payload files changed, missing or added; do not install an unverified bundle')
    return dict(package_verified=True,files=len(actual))


def ndk_default():
    if os.environ.get('ROYALE_NDK_BIN'):return Path(os.environ['ROYALE_NDK_BIN']).expanduser()
    sdk=Path(os.environ.get('ANDROID_SDK_ROOT',str(Path.home()/'Library/Android/sdk')))
    return sdk/'ndk/30.0.16248370/toolchains/llvm/prebuilt/darwin-x86_64/bin'


def sdk_path(explicit=None):
    if explicit:return Path(explicit).expanduser().resolve()
    return Path(subprocess.check_output(['xcrun','--sdk','macosx','--show-sdk-path'],text=True,timeout=10).strip())


def doctor(args):
    cfg={}
    if args.target:
        path=args.target.expanduser().resolve()/'deploy-config.json'
        if path.is_file():cfg=json.loads(path.read_text())
    ndk=Path(args.ndk_bin or cfg.get('ndk_bin') or ndk_default()).expanduser().resolve()
    version=platform.mac_ver()[0].split('.')
    checks=dict(host=platform.system()=='Darwin' and platform.machine()=='arm64' and bool(version[0]) and int(version[0])>=14,
                python=sys.version_info>=(3,12),adb=os.access(cfg['adb_path'],os.X_OK) if cfg.get('adb_path') else bool(shutil.which('adb')),
                xcrun=bool(shutil.which('xcrun')),lldb=os.access('/usr/bin/lldb',os.X_OK),
                codesign=bool(shutil.which('codesign')),
                ndk_compiler=(ndk/'aarch64-linux-android24-clang++').is_file(),
                ndk_readelf=(ndk/'llvm-readelf').is_file(),
                ndk_debugger=len(list(ndk.parent.glob('lib/clang/*/lib/linux/aarch64/lldb-server')))==1)
    source_properties=ndk.parents[4]/'source.properties'
    checks['ndk_revision']=source_properties.is_file() and '30.0.16248370' in source_properties.read_text()
    try:
        sdk=sdk_path(args.sdk);checks['macos_sdk']=sdk.is_dir()
        checks['swiftc']=subprocess.run(['xcrun','--find','swiftc'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10).returncode==0
    except (OSError,subprocess.SubprocessError):sdk=None;checks['macos_sdk']=checks['swiftc']=False
    if args.target:
        target=args.target.expanduser().resolve()
        checks['deployment_config']=(target/'deploy-config.json').is_file()
        checks['app']=(target/'apps/官服HTML回放.app/Contents/MacOS/ReplayConsole').is_file()
        checks['runtime_prepared']=(target/'runtime/native/runtime-profile.json').is_file()
    result=dict(checks=checks,ready=all(checks.values()),ndk_bin=str(ndk),sdk=str(sdk) if sdk else None,
                network_requests=False,device_contacted=False)
    print(json.dumps(result,ensure_ascii=False,indent=2));return result


def install(args):
    verify_package()
    if not doctor(argparse.Namespace(target=None,ndk_bin=args.ndk_bin,sdk=args.sdk))['ready']:
        raise RuntimeError('install prerequisites missing; see references/deployment.md')
    target=args.target.expanduser().absolute()
    if target.exists() or target.is_symlink():raise FileExistsError('target already exists; choose a new named directory')
    if target==Path('/') or len(target.parts)<3:raise ValueError('specific deployment directory required')
    shutil.copytree(PAYLOAD,target)
    venv.EnvBuilder(with_pip=False,symlinks=True).create(target/'.venv')
    ndk=Path(args.ndk_bin or ndk_default()).expanduser().resolve()
    vm=Path(args.vm_dir).expanduser().resolve();identifier=uuid.uuid4().hex
    cfg=dict(ndk_bin=str(ndk),vm_dir=str(vm),instance_name=args.instance_name,
             deployment_id=identifier,debug_port=49000+int(identifier[:8],16)%10000,adb_path=shutil.which('adb'),
             python=str(target/'.venv/bin/python3'),desktop_app=str(target/'apps/官服HTML回放.app'))
    (target/'deploy-config.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n')
    root=target/'official-web-replay';app=target/'apps/官服HTML回放.app';contents=app/'Contents'
    macos=contents/'MacOS';macos.mkdir(parents=True)
    plist=dict(CFBundleName='官服HTML回放',CFBundleDisplayName='官服HTML回放',CFBundleExecutable='ReplayConsole',
               CFBundleIdentifier='local.royale.htmlreplay.console',CFBundlePackageType='APPL',
               CFBundleShortVersionString='1.1.0',LSMinimumSystemVersion='14.0',
               RoyaleProjectRoot=str(root),RoyalePython=cfg['python'],RoyaleDeploymentID=identifier,NSHighResolutionCapable=True)
    with (contents/'Info.plist').open('wb') as f:plistlib.dump(plist,f)
    sdk=sdk_path(args.sdk)
    for sources,name in ((['ReplayConsole.swift','RoyaleBrowser.swift'],'ReplayConsole'),(['ReplayBridge.swift'],'ReplayBridge')):
        subprocess.run(['xcrun','swiftc',*(['-parse-as-library'] if name=='ReplayBridge' else []),'-sdk',str(sdk),'-target','arm64-apple-macosx14.0',
            *[str(root/s) for s in sources],'-o',str(macos/name)],check=True,timeout=120)
    subprocess.run(['codesign','--force','--sign','-','--identifier',plist['CFBundleIdentifier'],str(app)],check=True,timeout=30)
    subprocess.run(['codesign','--verify','--strict',str(app)],check=True,timeout=30)
    receipt=dict(desktop_installed=True,app=str(app),target=str(target),runtime_prepared=False,
                 emulator_started=False,network_changed=False,playback_tested=False)
    (target/'deployment-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(receipt,ensure_ascii=False,indent=2))


def register_bridge(args):
    if not args.confirm_browser_registration:raise ValueError('explicit confirmed browser-registration flag required')
    target=args.target.expanduser().resolve();cfg=json.loads((target/'deploy-config.json').read_text())
    host=Path(cfg['desktop_app'])/'Contents/MacOS/ReplayBridge'
    if not host.is_file():raise ValueError('install and compile the bridge first')
    browser='Microsoft Edge' if args.browser=='edge' else 'Google/Chrome'
    folder=Path.home()/'Library/Application Support'/browser/'NativeMessagingHosts'
    path=folder/'local.royale.htmlreplay.json'
    value=dict(name='local.royale.htmlreplay',description='Click-scoped RoyaleAPI HTML replay bridge',
               path=str(host),type='stdio',allowed_origins=['chrome-extension://dbjcdkkejbaccfpnicafnkjaehkjhkjf/'])
    if path.exists():
        if json.loads(path.read_text())!=value:raise FileExistsError('different browser registration exists; not overwritten')
    else:
        folder.mkdir(parents=True,exist_ok=True)
        with path.open('x') as f:json.dump(value,f,ensure_ascii=False,indent=2)
    print(json.dumps(dict(registered=str(path),extension_folder=str(target/'official-web-replay/browser-extension'),
                         extension_install_requires_user_confirmation=True),ensure_ascii=False))


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('verify-package')
    d=sub.add_parser('doctor');d.add_argument('--target',type=Path);d.add_argument('--ndk-bin');d.add_argument('--sdk')
    i=sub.add_parser('install');i.add_argument('--target',type=Path,required=True);i.add_argument('--ndk-bin')
    i.add_argument('--vm-dir',required=True);i.add_argument('--instance-name',required=True);i.add_argument('--sdk')
    b=sub.add_parser('register-bridge');b.add_argument('--target',type=Path,required=True)
    b.add_argument('--browser',choices=('edge','chrome'),required=True);b.add_argument('--confirm-browser-registration',action='store_true')
    args=p.parse_args()
    if args.command=='verify-package':print(json.dumps(verify_package()))
    elif args.command=='doctor':
        if not doctor(args)['ready']:raise SystemExit(2)
    elif args.command=='install':install(args)
    else:register_bridge(args)


if __name__=='__main__':main()
