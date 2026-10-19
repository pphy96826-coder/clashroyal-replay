"""Local Windows migration wizard. Uses only the bundle and one selected MuMu instance."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import shutil
import struct
import subprocess
import sys
import threading
import time
import uuid
import webbrowser

ROOT=Path(__file__).resolve().parent.parent
APP=ROOT/'app';CORE=APP/'official-web-replay';TOOLS=ROOT/'tools';STATE=ROOT/'state'
PYTHON=TOOLS/'python/python.exe';PYTHONW=TOOLS/'python/pythonw.exe'
NDK=TOOLS/'android-ndk-r27d/toolchains/llvm/prebuilt/windows-x86_64/bin'
ADB=TOOLS/'adb/adb.exe';CONFIG=APP/'deploy-config.json'
DEFAULT_MANAGER=Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Netease/MuMu/nx_main/MuMuManager.exe'

def run(command,timeout=30):
    p=subprocess.run([str(v) for v in command],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
        text=True,encoding='utf-8',errors='replace',timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if p.returncode:raise RuntimeError(p.stdout[-5000:] or '步骤失败：'+str(command[0]))
    return p.stdout

def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def checked_instance(name,port):
    if not isinstance(name,str) or not name.strip():raise ValueError('请填写实例名称')
    if type(port) is not int or not 1024<=port<=65535:raise ValueError('ADB 端口必须是 1024-65535 的整数')
    return dict(schema='royale-replay.local-binding.v1',vmName=name.strip(),adbPort=port)

def list_instances(manager):
    manager=Path(manager)
    if not manager.is_file():raise FileNotFoundError('请先选择 MuMuManager.exe')
    version=read_text_json(run([manager,'version']))['version']
    rows=read_text_json(run([manager,'info','-v','all']))
    return version,rows

def read_text_json(text):
    start=text.find('{');end=text.rfind('}')
    if start<0 or end<start:raise ValueError('MuMu 没有返回可识别的实例信息')
    return json.loads(text[start:end+1])

def configure(name,port,manager=None,index=None):
    if platform.system()!='Windows' or platform.machine().lower() not in ('amd64','x86_64'):raise ValueError('需要 Windows x64')
    selection=checked_instance(name,port)
    if manager:
        version,rows=list_instances(manager)
        if version!='6.6.4.0':raise ValueError('本包实测 MuMu 6.6.4.0；当前为 '+version+'。请使用匹配版本，勿跳过系统库校验。')
        if index is not None:
            row=rows.get(str(index),{})
            if not row.get('is_android_started'):raise ValueError('请先启动所选的 Android 12 实例')
            if row.get('android_version')!='12.0' or row.get('adb_port')!=port or row.get('name')!=name:
                raise ValueError('实例名称、端口或 Android 版本与 MuMu 实际信息不一致')
    for path in (PYTHON,PYTHONW,ADB,NDK/'clang++.exe',NDK/'lldb.exe'):
        if not path.is_file():raise FileNotFoundError('环境文件不完整：'+str(path))
    STATE.mkdir(exist_ok=True);binding=STATE/'device.json';save(binding,selection)
    previous=read(CONFIG) if CONFIG.exists() else {}
    same_path=previous.get('python')==str(PYTHON)
    identifier=previous.get('deployment_id') if same_path else uuid.uuid4().hex
    if not identifier:identifier=uuid.uuid4().hex
    cfg=dict(deployment_id=identifier,debug_port=49000+int(identifier[:8],16)%10000,
        ndk_bin=str(NDK),adb_path=str(ADB),lldb_path=str(NDK/'lldb.exe'),device_binding_file=str(binding),
        instance_name=selection['vmName'],python=str(PYTHON),platform='windows-x64',
        browser_bridge_enabled=bool(previous.get('browser_bridge_enabled') and same_path),native_transport='mumu-nativebridge-v1')
    save(CONFIG,cfg)
    save(STATE/'setup-selection.json',dict(manager=str(manager or ''),index=str(index) if index is not None else '',
        configured_at=time.strftime('%Y-%m-%d %H:%M:%S'),bundle_root=str(ROOT)))
    return '已保存本机路径和所选实例；未创建实例、未改变 Root 设置。'

def doctor():return run([PYTHON,'-X','utf8',CORE/'windows_doctor.py','--config',CONFIG])

def archive_owned(path,destination):
    path=Path(path);destination=Path(destination)
    absolute=path.resolve();app=APP.resolve()
    if path.is_symlink() or absolute==app or not absolute.is_relative_to(app):raise ValueError('拒绝移动包外目录')
    if not destination.resolve().is_relative_to(STATE.resolve()):raise ValueError('备份目录必须在本包 state 内')
    if path.exists():destination.parent.mkdir(parents=True,exist_ok=True);path.rename(destination)

def prepare_runtime():
    cfg=read(CONFIG);binding=read(cfg['device_binding_file']);serial='127.0.0.1:'+str(binding['adbPort'])
    adb=[ADB,'-s',serial];run([ADB,'connect',serial],10)
    uid=run(adb+['shell','id','-u'],10).strip()
    if uid!='0':
        run(adb+['root'],15)
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            try:
                run([ADB,'connect',serial],5)
                if run(adb+['shell','id','-u'],5).strip()=='0':break
            except RuntimeError:pass
            time.sleep(.5)
        else:raise RuntimeError('实例未提供 Root 调试。请在 MuMu 开启 Root 并重启该实例后再试。')
    backup=STATE/('runtime-backup-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
    archive_owned(APP/'runtime/native',backup/'native')
    for source,name in ((APP/'offline-private-map/build/assets.h','assets.h'),(APP/'offline-private-layout/build/objects.h','objects.h')):
        archive_owned(source,backup/name)
    return run([PYTHON,'-X','utf8',CORE/'prepare_runtime.py','--config',CONFIG],420)

def register_bridge(replace=False):
    import winreg
    cfg=read(CONFIG);folder=APP/'browser-bridge';folder.mkdir(exist_ok=True)
    executable=folder/'RoyaleReplayNativeHost.exe'
    if not executable.is_file():raise FileNotFoundError('缺少预编译原生消息宿主')
    manifest=folder/'local.royale.htmlreplay.json'
    registry=r'Software\Microsoft\Edge\NativeMessagingHosts\local.royale.htmlreplay'
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,registry) as key:previous=winreg.QueryValue(key,None)
        if Path(previous).resolve()!=manifest.resolve():
            if not replace:raise RuntimeError('已有其他目录的回放桥接。确认切换后再次安装。')
            save(STATE/('previous-browser-host-'+time.strftime('%Y%m%d-%H%M%S')+'.json'),dict(registry=registry,previous=previous))
    except FileNotFoundError:pass
    extension=read(ROOT/'browser-extension/manifest.json')
    digest=hashlib.sha256(base64.b64decode(extension['key'])).digest()[:16]
    identifier=''.join(chr(97+(v>>4))+chr(97+(v&15)) for v in digest)
    save(folder/'host-launch.json',dict(python=str(PYTHON),script=str(CORE/'windows_native_host.py')))
    save(manifest,dict(name='local.royale.htmlreplay',description='Local MuMu replay console',path=str(executable),
        type='stdio',allowed_origins=['chrome-extension://'+identifier+'/']))
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,registry) as key:winreg.SetValueEx(key,'',0,winreg.REG_SZ,str(manifest))
    cfg['browser_bridge_enabled']=True;save(CONFIG,cfg)
    return '已连接当前用户的 Edge 桥接。请手动加载文件夹：\n'+str(ROOT/'browser-extension')

def launch():
    if not CONFIG.is_file():raise RuntimeError('请先运行 00-Install.cmd 并保存配置')
    cfg=read(CONFIG)
    if cfg['python']!=str(PYTHON):raise RuntimeError('目录已移动，请在安装向导中重新保存配置并准备运行时')
    if not (APP/'runtime/native/runtime-profile.json').is_file():raise RuntimeError('请先在安装向导中准备当前实例的运行时')
    subprocess.Popen([str(PYTHONW),'-X','utf8',str(CORE/'windows_console.py')],cwd=CORE,
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return '控制台已打开'

def self_test():
    STATE.mkdir(exist_ok=True);folder=STATE/('self-test-'+uuid.uuid4().hex[:8]);folder.mkdir()
    save(folder/'device.json',checked_instance('离线环境校验',16384))
    cfg=dict(deployment_id=uuid.uuid4().hex,debug_port=58000,ndk_bin=str(NDK),adb_path=str(ADB),lldb_path=str(NDK/'lldb.exe'),
        device_binding_file=str(folder/'device.json'),instance_name='离线环境校验',python=str(PYTHON),native_transport='mumu-nativebridge-v1')
    save(folder/'config.json',cfg)
    env=dict(os.environ,ROYALE_REPLAY_CONFIG=str(folder/'config.json'),PYTHONUTF8='1')
    command=[str(PYTHON),'-X','utf8',str(Path(__file__).resolve()),'_compile-test',str(folder/'result.json')]
    p=subprocess.run(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,
        encoding='utf-8',errors='replace',env=env,timeout=100,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if p.returncode:raise RuntimeError(p.stdout)
    print(p.stdout,flush=True);return read(folder/'result.json')

def compile_test(destination):
    sys.path.insert(0,str(CORE))
    import tkinter
    from windows_doctor import inspect
    from portable_config import CONFIG as selected
    from mumu_runtime import compile_helpers
    report=inspect(selected)
    if not report['host_ready']:raise RuntimeError(json.dumps(report,ensure_ascii=False))
    tcl=tkinter.Tcl();host,guest,exports=compile_helpers(Path(destination).parent/'native-test')
    result=dict(passed=True,device_contacted=False,python=sys.version.split()[0],tcl=tcl.eval('info patchlevel'),
        host_ready=True,host_helper_bytes=host.stat().st_size,guest_helper_bytes=guest.stat().st_size,
        java=run([TOOLS/'jdk17/bin/java.exe','-version']).splitlines()[0],
        android_build_tools=run([TOOLS/'android-build-tools37/aapt2.exe','version']).strip(),
        adb=run([ADB,'version']).splitlines()[0],native_host_protocol=test_native_host(Path(destination).parent),bundle_root=str(ROOT))
    save(destination,result);print(json.dumps(result,ensure_ascii=False))

def test_native_host(folder):
    # Exercise the real .NET launcher with stdin left open, as Edge does.
    folder=folder/'host-pipe-test';folder.mkdir()
    executable=folder/'RoyaleReplayNativeHost.exe'
    shutil.copy2(APP/'browser-bridge/RoyaleReplayNativeHost.exe',executable)
    save(folder/'host-launch.json',dict(python=str(PYTHON),script=str(CORE/'windows_native_host.py')))
    p=subprocess.Popen([str(executable),'chrome-extension://dbjcdkkejbaccfpnicafnkjaehkjhkjf/'],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    answer=queue.Queue()
    def receive():
        try:
            header=p.stdout.read(4)
            if len(header)!=4:raise RuntimeError('原生宿主未返回消息，请检查 .NET Framework 4.x')
            size=struct.unpack('<I',header)[0]
            if not 0<size<65536:raise RuntimeError('原生宿主消息长度异常')
            answer.put(json.loads(p.stdout.read(size)))
        except Exception as error:answer.put(error)
    threading.Thread(target=receive,daemon=True).start()
    try:
        body=b'{"command":"launch"}'
        p.stdin.write(struct.pack('<I',len(body))+body);p.stdin.flush()
        reply=answer.get(timeout=12)
        if isinstance(reply,Exception):raise reply
        if reply.get('ok') is not False or reply.get('error')!='browser bridge is not enabled':
            raise RuntimeError('离线原生消息自检结果异常：'+str(reply))
        return 'passed; .NET launcher, framed input/output, open-stdin flush'
    finally:
        p.stdin.close()
        try:p.wait(timeout=5)
        except subprocess.TimeoutExpired:p.kill();p.wait()

def verify_manifest():
    manifest=read(ROOT/'manifest.json');failed=[];count=0
    for relative,item in manifest['files'].items():
        path=(ROOT/relative).resolve()
        if not path.is_relative_to(ROOT.resolve()):raise ValueError('校验清单含包外路径')
        if os.name=='nt':path=Path('\\\\?\\'+str(path))
        if not path.is_file() or path.stat().st_size!=item['bytes']:failed.append(relative);continue
        h=hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda:stream.read(4*1024*1024),b''):h.update(chunk)
        if h.hexdigest()!=item['sha256']:failed.append(relative)
        count+=1
    if failed:raise RuntimeError('校验不一致：\n'+'\n'.join(failed[:20]))
    print('文件校验通过：'+str(count)+' 个文件；设备未连接。')

def gui():
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox,scrolledtext
    app=tk.Tk();app.title('MuMu 回放环境安装向导');app.geometry('960x760')
    ttk.Label(app,text='MuMu 回放环境安装向导',font=('Microsoft YaHei UI',21)).pack(anchor='w',padx=24,pady=(20,5))
    ttk.Label(app,text='先启动 MuMu 的 Android 12 实例，再依次完成下方四步。仅操作你选定的实例。').pack(anchor='w',padx=24)
    manager=tk.StringVar(value=str(DEFAULT_MANAGER));name=tk.StringVar();port=tk.StringVar();chosen=tk.StringVar();status=tk.StringVar(value='准备配置')
    if (STATE/'device.json').exists():
        saved=read(STATE/'device.json');name.set(saved['vmName']);port.set(str(saved['adbPort']))
    frame=ttk.Frame(app);frame.pack(fill='x',padx=24,pady=15)
    ttk.Label(frame,text='MuMu 管理程序').grid(row=0,column=0,sticky='w')
    ttk.Entry(frame,textvariable=manager).grid(row=0,column=1,sticky='ew',padx=8)
    def browse():
        value=filedialog.askopenfilename(title='选择 MuMuManager.exe',filetypes=[('MuMu 管理程序','MuMuManager.exe')])
        if value:manager.set(value)
    ttk.Button(frame,text='选择…',command=browse).grid(row=0,column=2)
    ttk.Label(frame,text='实例').grid(row=1,column=0,sticky='w',pady=10)
    combo=ttk.Combobox(frame,textvariable=chosen,state='readonly');combo.grid(row=1,column=1,sticky='ew',padx=8)
    rows={};versions={}
    def refresh():
        try:
            version,items=list_instances(manager.get());rows.clear()
            for index,row in items.items():
                label=index+' · '+row.get('name','')+' · '+('已运行' if row.get('is_android_started') else '未启动')
                rows[label]=row
            combo['values']=list(rows)
            running=[k for k,v in rows.items() if v.get('is_android_started')]
            if len(running)==1:chosen.set(running[0]);select()
            status.set('MuMu 版本 '+version+'；请选择要使用的 Android 12 实例')
        except Exception as error:messagebox.showerror('未能读取实例',str(error))
    def select(event=None):
        row=rows.get(chosen.get(),{});name.set(row.get('name',''));port.set(str(row.get('adb_port','')))
    combo.bind('<<ComboboxSelected>>',select)
    ttk.Button(frame,text='读取实例',command=refresh).grid(row=1,column=2)
    ttk.Label(frame,text='实例名称').grid(row=2,column=0,sticky='w');ttk.Entry(frame,textvariable=name).grid(row=2,column=1,sticky='ew',padx=8)
    ttk.Label(frame,text='本机 ADB 端口').grid(row=3,column=0,sticky='w',pady=10);ttk.Entry(frame,textvariable=port).grid(row=3,column=1,sticky='ew',padx=8)
    frame.columnconfigure(1,weight=1)
    actions=ttk.Frame(app);actions.pack(fill='x',padx=24,pady=8);inbox=queue.Queue();buttons=[]
    log=scrolledtext.ScrolledText(app,font=('Consolas',10),wrap='word');log.pack(fill='both',expand=True,padx=24,pady=8)
    ttk.Label(app,textvariable=status,wraplength=910).pack(fill='x',padx=24,pady=7)
    def work(label,action):
        for button in buttons:button.configure(state='disabled')
        status.set(label+'…')
        def execute():
            try:inbox.put((True,label,action()))
            except Exception as error:inbox.put((False,label,str(error)))
        threading.Thread(target=execute,daemon=False).start()
    def save_config():
        try:
            selected_name=name.get();selected_port=int(port.get());selected_manager=manager.get();index=rows.get(chosen.get(),{}).get('index')
            work('保存配置',lambda:configure(selected_name,selected_port,selected_manager or None,index))
        except Exception as error:messagebox.showerror('配置无效',str(error))
    def runtime():
        if messagebox.askyesno('准备所选实例运行时','请先在 MuMu 开启 Root、重启该实例，并安装匹配的腾讯 38.4.2 客户端。\n本步骤使用 Root 调试访问读取游戏安装包，并写入本项目的调试组件；不会登录账号或创建对局。\n已有本包运行时会移入 state 备份。是否继续？'):
            work('准备运行时（可能需要数分钟）',prepare_runtime)
    def bridge():
        if messagebox.askyesno('连接 Edge 插件','将当前用户的回放插件桥接连接到此目录。已有其他目录的回放桥接会先记录备份再切换。是否继续？'):
            work('连接 Edge 桥接',lambda:register_bridge(True))
    for label,action in [('1 保存配置',save_config),('2 检查环境',lambda:work('检查环境',doctor)),('3 准备运行时',runtime),('4 连接 Edge 插件',bridge),('打开控制台',lambda:work('打开控制台',launch))]:
        button=ttk.Button(actions,text=label,command=action);button.pack(side='left',padx=(0,8));buttons.append(button)
    extra=ttk.Frame(app);extra.pack(fill='x',padx=24,pady=(0,15))
    ttk.Button(extra,text='打开图文教程',command=lambda:os.startfile(str(ROOT/'docs/安装教程.html'))).pack(side='left')
    ttk.Button(extra,text='MuMu 官方下载',command=lambda:webbrowser.open('https://mumu.163.com/download/')).pack(side='left',padx=8)
    ttk.Button(extra,text='显示插件文件夹',command=lambda:os.startfile(str(ROOT/'browser-extension'))).pack(side='left')
    def poll():
        while not inbox.empty():
            ok,label,value=inbox.get();status.set(label+('完成' if ok else '失败'))
            log.insert('end','\n'+label+'\n'+str(value)+'\n');log.see('end')
            for button in buttons:button.configure(state='normal')
        app.after(150,poll)
    app.after(150,poll);app.mainloop()

def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command')
    c=sub.add_parser('configure');c.add_argument('--name',required=True);c.add_argument('--port',type=int,required=True);c.add_argument('--manager',type=Path);c.add_argument('--index')
    for value in ('doctor','prepare','launch','self-test','verify','gui'):sub.add_parser(value)
    b=sub.add_parser('bridge');b.add_argument('--replace-existing',action='store_true')
    t=sub.add_parser('_compile-test');t.add_argument('destination',type=Path)
    a=p.parse_args()
    if a.command in (None,'gui'):gui();return
    if a.command=='configure':print(configure(a.name,a.port,a.manager,a.index))
    elif a.command=='doctor':print(doctor())
    elif a.command=='prepare':print(prepare_runtime())
    elif a.command=='bridge':print(register_bridge(a.replace_existing))
    elif a.command=='launch':print(launch())
    elif a.command=='self-test':print(json.dumps(self_test(),ensure_ascii=False,indent=2))
    elif a.command=='verify':verify_manifest()
    elif a.command=='_compile-test':compile_test(a.destination)

if __name__=='__main__':main()
