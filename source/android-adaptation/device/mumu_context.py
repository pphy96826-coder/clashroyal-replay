"""Accept a host syscall wait frame before the first translated expression.

This is observation only: no PC/register edits, calls, breakpoints or retries.
The attach owner may detach and freshly sample the same generation BEFORE any
expression or component load. A failed expression is never sampled/repeated.
"""
HOST_LIBC='/apex/com.android.runtime/lib64/bionic/libc.so'

def host_wait_mapping(pc,maps):
    if type(pc) is not int or pc<2:return False
    for line in maps.splitlines():
        parts=line.split()
        if len(parts)<6 or parts[-1]!=HOST_LIBC or 'x' not in parts[1]:continue
        low,high=(int(v,16) for v in parts[0].split('-'))
        if low<=pc-2 and pc<high:return True
    return False

def ready(lldb,process,pid,maps):
    if not process.IsValid() or process.GetProcessID()!=pid or process.GetState()!=lldb.eStateStopped:
        raise RuntimeError('MuMu context requires the exact stopped process')
    thread=process.GetThreadByID(pid)
    if not thread.IsValid() or thread.GetThreadID()!=pid:raise RuntimeError('MuMu main thread absent')
    if thread.GetStopReason()==lldb.eStopReasonSignal and thread.GetStopReasonDataCount():
        if thread.GetStopReasonDataAtIndex(0) not in (0,19):raise RuntimeError('MuMu signal stop is not a fresh attach; never resume a fault')
    frame=thread.GetFrameAtIndex(0)
    if not frame.IsValid():raise RuntimeError('MuMu main frame absent')
    pc=frame.GetPC();evidence=dict(thread_id=pid,frame_pc=hex(pc),host_syscall_wait=False)
    if not host_wait_mapping(pc,maps):return False,evidence
    error=lldb.SBError();raw=process.ReadMemory(pc-2,2,error)
    if not error.Success() or len(raw)!=2:raise RuntimeError('MuMu wait instruction unreadable')
    evidence['host_syscall_wait']=raw==b'\x0f\x05'
    return evidence['host_syscall_wait'],evidence
