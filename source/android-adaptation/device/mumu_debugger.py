"""Phone-local x86 server over an inherited socketpair; no listening port."""
import os,socket,subprocess,time
from mumu_platform import enabled,host_binary


class Attachment:
    def __init__(self,lldb,target,listener,pid,log):
        if not enabled() or type(pid) is not int or pid<=0:raise ValueError('verified MuMu PID required')
        self.server=None;self.process=None;self.client=None;self.lldb=lldb
        client,server=socket.socketpair(socket.AF_UNIX,socket.SOCK_STREAM)
        self.client=client
        try:
            environment=dict(os.environ)
            for key in ('LD_LIBRARY_PATH','LD_PRELOAD'):environment.pop(key,None)
            self.server=subprocess.Popen([str(host_binary('lldb-server')),'gdbserver','--fd',str(server.fileno()),'--attach',str(pid)],
                stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,pass_fds=(server.fileno(),),env=environment)
            server.close()
            error=lldb.SBError()
            self.process=target.ConnectRemote(listener,'fd://'+str(client.fileno()),'gdb-remote',error)
            if not error.Success() or not self.process.IsValid() or self.process.GetProcessID()!=pid:
                raise RuntimeError('local x86 debug connection failed: '+str(error))
            if target.GetTriple().split('-')[0] not in ('x86_64','amd64'):
                raise RuntimeError('local x86 debug target differs')
            # Embedded LLDB has no CLI event thread. Removing the attach event
            # commits its public stopped state; this never resumes the target.
            deadline=time.monotonic()+10
            while self.process.GetState()!=lldb.eStateStopped and time.monotonic()<deadline:
                if self.server.poll() is not None:raise RuntimeError('owned debug server exited during attach')
                event=lldb.SBEvent();listener.WaitForEvent(1,event)
                if lldb.SBProcess.EventIsProcessEvent(event):
                    state=lldb.SBProcess.GetStateFromEvent(event)
                    if state in (lldb.eStateCrashed,lldb.eStateExited,lldb.eStateDetached):
                        raise RuntimeError('owned debug target entered terminal state '+str(state))
            if self.process.GetState()!=lldb.eStateStopped:raise RuntimeError('owned debug attach did not report stopped')
        except BaseException:
            if self.process and (not self.process.IsValid() or not self.process.GetProcessID()):self.process=None
            self.close();raise
        finally:
            server.close()

    def close(self):
        if self.process and self.process.IsValid() and self.process.GetState() not in (self.lldb.eStateDetached,self.lldb.eStateExited):
            error=self.process.Detach()
            if not error.Success():raise RuntimeError('local x86 debugger detach failed: '+str(error))
        self.process=None
        # gdbserver waits for EOF while our inherited socket remains open.
        # Close our endpoint after confirmed detach, before waiting for exit;
        # otherwise every successful native component pays the 5 s timeout.
        if self.client:
            try:self.client.shutdown(socket.SHUT_RDWR)
            except OSError:pass
            self.client.close();self.client=None
        if self.server:
            try:self.server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server.terminate();self.server.wait(timeout=5)
            self.server=None
