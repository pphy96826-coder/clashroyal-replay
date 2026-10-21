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
        if not isinstance(path,str) or not re.fullmatch(r'/data/local/tmp/royale-phone-[0-9a-f]{32}/libphone_replay_(?:bootstrap|scene)\.so',path):
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
        self.translated=identity.get('native_transport')=='mumu-nativebridge-v1'
        if not self.translated:raise ValueError('this adapter requires explicit MuMu translation')
        from mumu_platform import enabled
        if not enabled():raise ValueError('unverified MuMu runtime')
        self.evidence={}
        self.allowed={int(pin['address'],0) for pin in loader['exports'].values()}
        self.allowed.add(int(identity['base'],0)+0xf5603c)
        if self.translated and self.target.GetTriple().split('-')[0] not in ('x86_64','amd64'):
            raise RuntimeError('MuMu translation requires an x86_64 debugger target')

    def authorize_component(self,functions):
        # Called only after the gate has checked the complete component export hashes.
        self.allowed.update(functions.values())

    def _evaluate(self,expression,stop_others=True):
        from device_expression import evaluate
        return evaluate(lldb,self.target,self.process,self.identity['pid'],expression,
                        stop_others=stop_others,evidence=self.evidence)

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
        from device_session import ReadOnlySession
        from mumu_runtime import publish_helpers,borrowed_bindings
        from mumu_platform import support
        from mumu_elf import Elf
        from mapped_elf import load_bias
        session=ReadOnlySession(self.identity);profile=publish_helpers(session)
        bridge=self.loader['mumu_bridge']
        for name,pin in bridge['host_loader_exports'].items():
            if hashlib.sha256(session.read(int(pin['address'],0),pin['size'])).hexdigest()!=pin['sha256']:
                raise RuntimeError('host loader changed: '+name)
        api=borrowed_bindings(session)
        host_path=profile['host_device_path'];guest_path=profile['guest_device_path']
        def borrowed_string_call(address,signature,value,tail=''):
            pointer=self._cstring(value)
            try:return self._host_call(address,signature,'(const char*)%dULL%s'%(pointer,tail),False)
            finally:self.process.DeallocateMemory(pointer)
        maps=session.verify().splitlines()
        if not any(len(line.split())>=6 and line.split()[-1]=='/system/lib64/libhoudini.so' for line in maps):
            raise RuntimeError('different or absent translator implementation')
        if not any(len(line.split())>=6 and line.split()[-1]==host_path for line in maps):
            handle=borrowed_string_call(int(bridge['host_loader_exports']['dlopen']['address'],0),
                'void*(*)(const char*,int)',host_path,',2')
            if not handle:
                pointer=self._host_call(int(bridge['host_loader_exports']['dlerror']['address'],0),'const char*(*)()')
                error=lldb.SBError();message=self.process.ReadCStringFromMemory(pointer,1024,error) if pointer else ''
                raise RuntimeError('owned x86_64 helper load failed: '+str(message))
            maps=session.verify().splitlines()
        local_host=support()/'helpers/librr_mumu_host.so'
        base=load_bias(maps,host_path,Elf(local_host.read_bytes(),machine=62));functions={}
        session=ReadOnlySession(self.identity)
        for name,pin in profile['host_exports'].items():
            address=base+int(pin['va'],0)
            if hashlib.sha256(session.read(address,pin['size'])).hexdigest()!=pin['sha256']:
                raise RuntimeError('owned helper export changed')
            functions[name]=address
        args=','.join(str(api[key])+'ULL' for key in ('bridge','state','vm'))
        if borrowed_string_call(functions['rr_mumu_bind_api'],
                'int(*)(const char*,unsigned long long,unsigned long long,unsigned long long)',guest_path,','+args)!=1:
            address=self._host_call(functions['rr_mumu_error'],'const char*(*)()')
            error=lldb.SBError();message=self.process.ReadCStringFromMemory(address,512,error)
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
