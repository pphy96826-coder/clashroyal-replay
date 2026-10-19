"""One framed browser request, restricted to this extension and local job queue."""
import base64
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parent
LIMIT=26*1024*1024

def extension_origin():
    manifest=json.loads((ROOT/'browser-extension/manifest.json').read_text(encoding='utf-8'))
    digest=hashlib.sha256(base64.b64decode(manifest['key'])).digest()[:16]
    identifier=''.join(chr(97+(v>>4))+chr(97+(v&15)) for v in digest)
    return 'chrome-extension://'+identifier+'/'

def read_message(stream):
    header=stream.read(4)
    if len(header)!=4:raise ValueError('missing native message header')
    size=struct.unpack('<I',header)[0]
    if not 0<size<=LIMIT:raise ValueError('native message exceeds bound')
    body=stream.read(size)
    if len(body)!=size:raise ValueError('short native message')
    doc=json.loads(body.decode('utf-8'))
    if not isinstance(doc,dict):raise ValueError('native message must be an object')
    return doc

def launch():
    from portable_config import config
    cfg=config()
    if cfg.get('browser_bridge_enabled') is not True:raise ValueError('browser bridge is not enabled')
    python=Path(cfg['python']).with_name('pythonw.exe')
    if not python.is_file():raise ValueError('desktop Python is unavailable')
    subprocess.Popen([str(python),'-X','utf8',str(ROOT/'windows_console.py')],cwd=ROOT,
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

def handle(doc,*,start_console=True,directory=None):
    from portable_config import bridge_queue,config
    from bridge_queue import valid_id,status_path,update_status
    if config().get('browser_bridge_enabled') is not True:raise ValueError('browser bridge is not enabled')
    folder=Path(directory) if directory is not None else bridge_queue()
    folder.mkdir(parents=True,exist_ok=True)
    command=doc.get('command')
    if command=='status':
        identifier=valid_id(doc.get('job_id'));path=status_path(folder,identifier)
        return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else dict(ok=True,state='missing',message='未找到本地任务')
    if command=='launch':
        if start_console:launch()
        return dict(ok=True,message='已打开 MuMu 回放控制台')
    if command!='capture-play':raise ValueError('unsupported browser command')
    from browser_capture import save_capture,replay_url
    from portable_config import local_data,deployment_id
    capture=save_capture(doc.get('html'),doc.get('url'),project=ROOT.parent/'vendor',
        directory=local_data()/'RoyaleReplayBridge'/deployment_id()/'captures')
    tag,url=replay_url(doc['url'])
    # A second popup request must not duplicate an unfinished publication.
    for candidate in folder.glob('*.json'):
        if candidate.name.endswith('.status.json'):continue
        previous=json.loads(candidate.read_text(encoding='utf-8'))
        state_path=status_path(folder,previous['job_id'])
        if previous.get('source_sha256')==capture['source_sha256'] and state_path.exists():
            state=json.loads(state_path.read_text(encoding='utf-8')).get('state')
            if state in ('queued','validating','preparing','playing'):
                if start_console:launch()
                return dict(ok=True,job_id=previous['job_id'],duplicate_suppressed=True)
    identifier=str(uuid.uuid4())
    raw=Path(capture['path']).read_bytes()
    with (folder/(identifier+'.html')).open('xb') as stream:stream.write(raw)
    job=dict(schema='official-web-replay.bridge-job.v1',job_id=identifier,command=command,
        source_url=url,replay_tag=tag,source_sha256=capture['source_sha256'])
    # queued is written last, so the worker cannot claim a partial job.
    with (folder/(identifier+'.json')).open('x',encoding='utf-8') as stream:json.dump(job,stream)
    update_status(folder,identifier,'queued','已接收网页回放，等待 MuMu 控制台校验。')
    reply=dict(ok=True,job_id=identifier,retained_action_count=capture['retained_action_count'])
    if start_console:
        try:launch()
        except Exception as error:reply['launch_warning']='请手动打开回放控制台：'+str(error)
    return reply

def main():
    if os.name=='nt':
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(),os.O_BINARY);msvcrt.setmode(sys.stdout.fileno(),os.O_BINARY)
    try:
        if len(sys.argv)<2 or sys.argv[1]!=extension_origin():raise ValueError('unrecognized browser extension origin')
        reply=handle(read_message(sys.stdin.buffer))
    except Exception as error:reply=dict(ok=False,error=str(error)[:4000])
    body=json.dumps(reply,ensure_ascii=False).encode('utf-8')
    sys.stdout.buffer.write(struct.pack('<I',len(body))+body);sys.stdout.buffer.flush()

if __name__=='__main__':main()
