"""Typed native/translated calls. ARM code never runs as an x86 LLDB expression."""
import hashlib
import json
import re
import subprocess
from pathlib import Path

import lldb

SIGNATURES={
    'unsigned long long(*)()':(1,0),
    'int(*)()':(2,0),
    'int(*)(unsigned long long,int,unsigned long long,unsigned long long,unsigned long long)':(3,5),
    'int(*)(void*)':(4,1),
    'void*(*)(const char*,int)':(5,2),
}


def integer(value):
    match=re.fullmatch(r'(?:\(void\*\))?(0x[0-9a-fA-F]+|[0-9]+)(?:ULL)?',value.strip())
    if not match:raise ValueError('only literal typed native arguments are accepted')
    token=match.group(1);result=int(token,16 if token.startswith('0x') else 10)
    if not 0<=result<1<<64:raise ValueError('native argument exceeds uint64')
    return result


def arguments(signature,text):
    if signature not in SIGNATURES:raise ValueError('unimplemented native call signature')
    op,count=SIGNATURES[signature]
    if op==5:
        path,end=json.JSONDecoder().raw_decode(text)
        if not isinstance(path,str) or not re.fullmatch(r'/data/local/tmp/royale_replay_[A-Za-z0-9_]+/[A-Za-z0-9_.-]+\.so',path):
            raise ValueError('only this deployment\'s native component may be loaded')
        rest=text[end:].strip()
        if rest!=',2':raise ValueError('only RTLD_NOW component loads are supported')
        return op,[path,2]
    parts=[] if not text.strip() else text.split(',')
    if len(parts)!=count:raise ValueError('native argument count changed')
    values=[integer(part) for part in parts]
    if op==3 and values[1]>0x7fffffff:raise ValueError('native PID must fit signed int')
    return op,values


class NativeExpression:
    def __init__(self,debugger,identity,loader,component):
        self.debugger=debugger;self.target=debugger.GetSelectedTarget();self.process=self.target.GetProcess()
        self.identity=identity;self.loader=loader;self.functions=None
        self.component_path=component['device_path']
        from portable_config import runtime_profile
        self.profile=runtime_profile()
        self.translated=self.profile.get('native_transport')=='mumu-nativebridge-v1'
        self.allowed={int(pin['address'],0) for pin in loader['exports'].values()}
        self.allowed.add(int(identity['base'],0)+0xf5603c)
        if self.translated and self.target.GetTriple().split('-')[0] not in ('x86_64','amd64'):
            raise RuntimeError('MuMu translation requires an x86_64 debugger target')

    def authorize_component(self,functions):
        # Called only after the gate has checked the complete component export hashes.
        self.allowed.update(functions.values())

    def _evaluate(self,expression,stop_others=True):
        thread=self.process.GetThreadByID(self.identity['pid'])
        if not thread.IsValid():raise RuntimeError('bound main thread absent')
        self.process.SetSelectedThread(thread)
        options=lldb.SBExpressionOptions();options.SetLanguage(lldb.eLanguageTypeC);options.SetAllowJIT(True)
        options.SetTimeoutInMicroSeconds(5000000);options.SetIgnoreBreakpoints(True)
        options.SetUnwindOnError(True);options.SetStopOthers(stop_others)
        value=self.target.EvaluateExpression(expression,options)
        if not value.GetError().Success():raise RuntimeError(str(value.GetError()))
        return value.GetValueAsUnsigned()

    def _cstring(self,value):
        raw=value.encode('utf-8')+b'\0'
        if len(raw)>4096:raise ValueError('native string exceeds bound')
        error=lldb.SBError();address=self.process.AllocateMemory(len(raw),lldb.ePermissionsReadable|lldb.ePermissionsWritable,error)
        if not error.Success() or not address:raise RuntimeError('cannot allocate bound call argument')
        if self.process.WriteMemory(address,raw,error)!=len(raw) or not error.Success():
            self.process.DeallocateMemory(address);raise RuntimeError('short native string write')
        return address

    def _host_call(self,address,signature,args='',stop_others=True):
        return self._evaluate('((%s)%dULL)(%s)'%(signature,address,args),stop_others)

    def _bind(self):
        bridge=self.loader['mumu_bridge'];profile=self.profile['mumu_bridge']
        from client_session import ReadOnlySession
        session=ReadOnlySession(self.identity)
        from mumu_runtime import validate_device
        validate_device(session.adb)
        for key in ('host','guest'):
            observed=subprocess.check_output(session.adb+['shell','sha256sum',profile[key+'_device_path']],text=True,timeout=10).split()[0]
            if observed!=profile[key+'_sha256']:raise RuntimeError('owned bridge binary changed: '+key)
        for name,pin in bridge['host_loader_exports'].items():
            if hashlib.sha256(session.read(int(pin['address'],0),pin['size'])).hexdigest()!=pin['sha256']:
                raise RuntimeError('host loader changed: '+name)
        host_path=profile['host_device_path'];guest_path=profile['guest_device_path']
        def borrowed_string_call(address,signature,value,tail=''):
            pointer=self._cstring(value)
            try:return self._host_call(address,signature,'(const char*)%dULL%s'%(pointer,tail),False)
            finally:self.process.DeallocateMemory(pointer)
        maps=session.verify().splitlines()
        from mumu_runtime import borrowed_bindings
        from portable_config import runtime_dir
        api=borrowed_bindings(session,maps,profile,runtime_dir())
        if not any(len(line.split())>=6 and line.split()[-1]=='/system/lib64/libhoudini.so' for line in maps):
            raise RuntimeError('game is using a different or absent translator implementation')
        if not any(len(line.split())>=6 and line.split()[-1]==host_path for line in maps):
            handle=borrowed_string_call(int(bridge['host_loader_exports']['dlopen']['address'],0),
                'void*(*)(const char*,int)',host_path,',2')
            if not handle:
                pointer=self._host_call(int(bridge['host_loader_exports']['dlerror']['address'],0),'const char*(*)()')
                error=lldb.SBError();message=self.process.ReadCStringFromMemory(pointer,1024,error) if pointer else ''
                raise RuntimeError('owned x86_64 helper load failed: '+str(message))
            maps=session.verify().splitlines()
        from mapped_elf import load_bias
        from elf_contract import Elf
        local_host=Path(__file__).resolve().parent.parent/'runtime/native/librr_mumu_host.so'
        if hashlib.sha256(local_host.read_bytes()).hexdigest()!=profile['host_sha256']:raise RuntimeError('local helper changed')
        base=load_bias(maps,host_path,Elf(local_host.read_bytes(),machine=62));functions={}
        # dlopen has added mappings since the previous bounded read snapshot.
        session=ReadOnlySession(self.identity)
        for name,pin in profile['host_exports'].items():
            address=base+int(pin['va'],0)
            if hashlib.sha256(session.read(address,pin['size'])).hexdigest()!=pin['sha256']:
                raise RuntimeError('helper export changed')
            functions[name]=address
        api_arguments=','.join(str(api[key])+'ULL' for key in ('bridge','state','vm'))
        if borrowed_string_call(functions['rr_mumu_bind_api'],
                'int(*)(const char*,unsigned long long,unsigned long long,unsigned long long)',guest_path,','+api_arguments)!=1:
            error_address=self._host_call(functions['rr_mumu_error'],'const char*(*)()')
            error=lldb.SBError();message=self.process.ReadCStringFromMemory(error_address,512,error)
            raise RuntimeError('MuMu bridge bind failed: '+str(message))
        self.functions=functions

    def __call__(self,address,signature,args='',stop_others=True):
        if not self.translated:return self._host_call(address,signature,args,stop_others)
        if type(address) is not int or address not in self.allowed:
            raise ValueError('translated address lacks a verified binding')
        op,values=arguments(signature,args)
        if op==5 and values[0]!=self.component_path:raise ValueError('component path differs from verified binding')
        if self.functions is None:self._bind()
        temporary=None
        if op==5:temporary=self._cstring(values[0]);values[0]=temporary
        values=values+[0]*(5-len(values))
        try:
            return self._host_call(self.functions['rr_mumu_call'],
                'unsigned long long(*)(unsigned long long,unsigned long long,unsigned long long,unsigned long long,unsigned long long,unsigned long long,unsigned long long)',
                ','.join(str(v)+'ULL' for v in [op,address]+values),stop_others)
        finally:
            if temporary:self.process.DeallocateMemory(temporary)
