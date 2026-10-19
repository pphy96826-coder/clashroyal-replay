"""Tk desktop front-end for the unchanged JSON worker protocol; no web server."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading

ROOT=Path(__file__).resolve().parent


def play_request(html,speed):
    path=Path(html).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() not in ('.html','.htm'):raise ValueError('请选择已有的 HTML 文件')
    value=float(speed)
    if value not in (.25,.5,1,2,4):raise ValueError('播放倍速不正确')
    return dict(command='play',html=str(path),speed=value)


class WorkerClient:
    def __init__(self,inbox):self.inbox=inbox;self.process=None
    def start(self):
        if self.process and self.process.poll() is None:return False
        from portable_config import config
        self.process=subprocess.Popen([config().get('python',sys.executable),'-X','utf8','-u',str(ROOT/'desktop_worker.py')],
            cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
            text=True,encoding='utf-8',bufsize=1,env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8'),
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        process=self.process
        def read():
            for line in process.stdout:
                try:self.inbox.put(json.loads(line))
                except ValueError:self.inbox.put(dict(event='log',value=line.rstrip()))
            self.inbox.put(dict(event='worker_exit',value=process.wait()))
        threading.Thread(target=read,daemon=True).start()
        return True
    def send(self,value):
        if not self.process or self.process.poll() is not None:raise RuntimeError('后台未启动')
        self.process.stdin.write(json.dumps(value,ensure_ascii=False)+'\n');self.process.stdin.flush()
    def shutdown(self):
        if self.process and self.process.poll() is None:
            self.send(dict(command='shutdown'))
            # Never kill/terminate an in-flight native task when closing UI.


def main():
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox,scrolledtext
    from portable_config import CONFIG,config,deployment_id
    mutex=None
    if os.name=='nt':
        import ctypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateMutexW.restype=ctypes.c_void_p
        mutex=kernel.CreateMutexW(None,False,'Local\\RoyaleReplayConsole_'+deployment_id())
        if not mutex:raise RuntimeError('无法创建控制台窗口锁')
        if ctypes.get_last_error()==183:
            kernel.CloseHandle(ctypes.c_void_p(mutex));return
    app=tk.Tk();app.title('官服 HTML 回放 · Windows 适配预览');app.geometry('1080x760')
    inbox=queue.Queue();client=WorkerClient(inbox);busy=False;running_tool=False;pending_play=None
    path=tk.StringVar();speed=tk.StringVar(value='1');status=tk.StringVar(value='就绪 · 尚未连接设备')
    ttk.Label(app,text='官服 HTML 战斗回放',font=('Microsoft YaHei UI',22)).pack(anchor='w',padx=24,pady=(20,8))
    ttk.Label(app,text='MuMu 当前实例 · 已接通网页一键播放与本地 HTML 导入。').pack(anchor='w',padx=24)
    row=ttk.Frame(app);row.pack(fill='x',padx=24,pady=16)
    ttk.Entry(row,textvariable=path).pack(side='left',fill='x',expand=True)
    def choose():
        selected=filedialog.askopenfilename(filetypes=[('回放 HTML','*.html *.htm')])
        if selected:path.set(selected)
    ttk.Button(row,text='选择 HTML…',command=choose).pack(side='left',padx=(12,0))
    tools=ttk.Frame(app);tools.pack(fill='x',padx=24,pady=4)
    def log(value):output.insert('end',str(value)+'\n');output.see('end')
    def tool(script):
        nonlocal running_tool
        if busy or running_tool:messagebox.showwarning('请等待','已有步骤正在运行');return
        if client.process and client.process.poll() is None:
            messagebox.showwarning('请先关闭重开控制台','后台已加载配置；请关闭重开后再运行检查或准备，避免并行操作。');return
        if script=='prepare_runtime.py' and not messagebox.askyesno('确认本地调试准备',
            '仅连接配置文件中明确选定的本机端口，读取你自己的客户端并准备调试组件。\n不创建战斗、不改网络、不自动获取权限。是否继续？'):return
        running_tool=True;status.set('正在运行 '+script)
        def work():
            try:
                process=subprocess.Popen([sys.executable,'-X','utf8',str(ROOT/script),'--config',str(CONFIG)],cwd=ROOT,
                    stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace')
                for line in process.stdout:inbox.put(dict(event='log',value=line.rstrip()))
                inbox.put(dict(event='tool_exit',value=process.wait()))
            except Exception as error:inbox.put(dict(event='tool_exit',value=str(error)))
        threading.Thread(target=work,daemon=False).start()
    ttk.Button(tools,text='检查环境（不连接设备）',command=lambda:tool('windows_doctor.py')).pack(side='left')
    ttk.Button(tools,text='准备本机运行时…',command=lambda:tool('prepare_runtime.py')).pack(side='left',padx=10)
    def play():
        nonlocal running_tool
        try:
            if running_tool or busy or pending_play:raise RuntimeError('请等待当前步骤完成')
            request=play_request(path.get(),speed.get());running_tool=True;status.set('核对主机条件…')
            def check():
                try:
                    from windows_doctor import inspect
                    report=inspect(CONFIG)
                    if not report['host_ready'] or not report['runtime_prepared']:raise RuntimeError('环境或运行时未就绪。请先执行检查和准备。')
                    inbox.put(dict(event='start_play',value=request))
                except Exception as error:inbox.put(dict(event='play_check_error',value=str(error)))
            threading.Thread(target=check,daemon=True).start()
        except Exception as error:messagebox.showerror('未开始播放',str(error))
    controls=ttk.Frame(app);controls.pack(fill='x',padx=24,pady=14)
    play_button=ttk.Button(controls,text='播放回放',command=play);play_button.pack(side='left')
    def stop():
        try:client.send(dict(command='stop'))
        except Exception as error:messagebox.showinfo('停止',str(error))
    ttk.Button(controls,text='停止 / 安全取消',command=stop).pack(side='left',padx=12)
    ttk.Label(controls,text='倍速').pack(side='left');ttk.Combobox(controls,textvariable=speed,values=['0.25','0.5','1','2','4'],state='readonly',width=7).pack(side='left',padx=8)
    end_controls=ttk.Frame(app)
    def replay():
        try:
            client.start();client.send(dict(command='replay'))
            end_controls.pack_forget();status.set('正在准备重新回放…')
        except Exception as error:status.set(str(error))
    def leave():
        try:client.send(dict(command='exit'))
        except Exception as error:status.set(str(error))
        end_controls.pack_forget();progress['value']=0
    replay_button=ttk.Button(end_controls,text='重新回放',command=replay);replay_button.pack(side='left')
    exit_button=ttk.Button(end_controls,text='退出回放',command=leave);exit_button.pack(side='left',padx=12)
    def return_to_console():
        app.deiconify();app.lift();app.attributes('-topmost',True)
        app.after(400,lambda:app.attributes('-topmost',False));app.focus_force()
    ttk.Label(app,textvariable=status,wraplength=1000).pack(anchor='w',padx=24,pady=6)
    progress=ttk.Progressbar(app,maximum=100);progress.pack(fill='x',padx=24,pady=8)
    output=scrolledtext.ScrolledText(app,font=('Consolas',10),wrap='word');output.pack(fill='both',expand=True,padx=24,pady=10)
    ttk.Label(app,text='实际战场在 MuMu 中显示。网页播放时点击 Edge 工具栏的“RoyaleAPI → 官服回放”插件。').pack(anchor='w',padx=24,pady=(0,14))
    def poll():
        nonlocal busy,running_tool,pending_play
        while not inbox.empty():
            doc=inbox.get();event=doc.get('event');value=doc.get('value')
            if event=='busy':
                busy=bool(value);play_button.configure(state='disabled' if busy else 'normal')
                replay_button.configure(state='disabled' if busy else 'normal')
                if not busy and pending_play:
                    request=pending_play;pending_play=None
                    try:client.send(request)
                    except (OSError,RuntimeError) as error:status.set(str(error));log(error)
            elif event=='start_play':
                running_tool=False
                try:
                    if client.start():pending_play=value;status.set('等待后台完成回放归属检查…')
                    else:client.send(value)
                except (OSError,RuntimeError) as error:status.set(str(error));log(error)
            elif event=='play_check_error':running_tool=False;status.set(str(value));log(value)
            elif event=='position':
                elapsed=value.get('tick',0)/20;duration=value.get('duration',1)
                progress['value']=min(100,100*elapsed/max(duration,1));status.set(f'原生实际进度 {elapsed:.1f} / {duration:.1f} 秒')
            elif event=='tool_exit':running_tool=False;status.set('步骤结束：'+str(value));log(status.get())
            elif event=='complete':
                progress['value']=100;status.set('回放已完成，正在刷新客户端…');return_to_console()
            elif event=='playback_ended':
                busy=False;pending_play=None;play_button.configure(state='normal')
                replay_button.configure(state='normal' if value.get('can_replay') else 'disabled')
                if value.get('reason')=='exit':end_controls.pack_forget()
                else:end_controls.pack(fill='x',padx=24,pady=4,before=output)
                status.set(value.get('message','已退出回放'));log(status.get());return_to_console()
            elif event in ('playing','resumed'):
                end_controls.pack_forget();status.set('正在 MuMu 中播放回放')
            elif event=='error':pending_play=None;status.set('失败：'+str(value));log(status.get())
            elif event=='worker_exit':
                busy=False;pending_play=None;play_button.configure(state='normal')
                status.set('后台已退出，可以重新播放。');log(status.get())
            elif event in ('status','ready','cancelled','stopped'):status.set(str(value));log(value)
            elif event=='match':log('已解析对局：'+json.dumps(value,ensure_ascii=False))
            elif event=='log':log(value)
            state_file=ROOT.parent/'console-ui-state.json'
            state_value=dict(event=event,status=status.get(),busy=busy,
                end_controls_visible=bool(end_controls.winfo_manager()),
                replay_enabled=str(replay_button.cget('state'))!='disabled',
                play_enabled=str(play_button.cget('state'))!='disabled')
            temporary=state_file.with_suffix('.tmp');temporary.write_text(json.dumps(state_value,ensure_ascii=False),encoding='utf-8')
            os.replace(temporary,state_file)
        app.after(120,poll)
    def close():
        if (busy or running_tool) and not messagebox.askyesno('仍在处理','关闭窗口不会强杀已提交任务；任务会安全结束。仍要关闭？'):return
        try:client.shutdown()
        except (OSError,RuntimeError):pass
        app.destroy()
    app.protocol('WM_DELETE_WINDOW',close)
    if config().get('browser_bridge_enabled'):
        client.start();status.set('正在连接网页播放桥接…')
    app.after(120,poll);app.mainloop()
    if mutex:kernel.CloseHandle(ctypes.c_void_p(mutex))


if __name__=='__main__':main()
