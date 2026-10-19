"""Register only this user's Edge native host; browser loading is a separate step."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);a=p.parse_args()
    if os.name!='nt':raise ValueError('Windows is required')
    import winreg
    config=a.config.resolve();cfg=json.loads(config.read_text(encoding='utf-8'))
    deployment=config.parent;core=deployment/'official-web-replay';folder=deployment/'browser-bridge'
    folder.mkdir(exist_ok=True)
    compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    executable=folder/'RoyaleReplayNativeHost.exe'
    subprocess.run([str(compiler),'/nologo','/target:exe','/platform:anycpu','/reference:System.Web.Extensions.dll',
        '/out:'+str(executable),str(core/'NativeHost.cs')],check=True,timeout=30)
    import base64
    extension=json.loads((core/'browser-extension/manifest.json').read_text(encoding='utf-8'))
    digest=hashlib.sha256(base64.b64decode(extension['key'])).digest()[:16]
    identifier=''.join(chr(97+(v>>4))+chr(97+(v&15)) for v in digest)
    host=folder/'local.royale.htmlreplay.json'
    registry=r'Software\Microsoft\Edge\NativeMessagingHosts\local.royale.htmlreplay'
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,registry) as key:previous=winreg.QueryValue(key,None)
        if Path(previous).resolve()!=host:raise ValueError('another replay deployment owns the native host registration')
    except FileNotFoundError:pass
    (folder/'host-launch.json').write_text(json.dumps(dict(python=cfg['python'],script=str(core/'windows_native_host.py')),indent=2),encoding='utf-8')
    manifest=dict(name='local.royale.htmlreplay',description='RoyaleAPI to local MuMu replay console',
        path=str(executable),type='stdio',allowed_origins=['chrome-extension://'+identifier+'/'])
    host.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,registry) as key:winreg.SetValueEx(key,'',0,winreg.REG_SZ,str(host))
    cfg['browser_bridge_enabled']=True
    config.write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    receipt=dict(native_host_registered=True,registry_scope='HKCU Edge',extension_id=identifier,
        extension_path=str(core/'browser-extension'),host_manifest=str(host),
        executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),browser_extension_loaded=False)
    (folder/'installation-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False))

if __name__=='__main__':main()
