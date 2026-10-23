"""Resolve hash-pinned MuMu guest and host loader bindings locally on Android."""
import hashlib,struct,json,os,stat,re
from pathlib import Path
from mumu_elf import Elf
from mapped_elf import load_bias
from mumu_platform import enabled,PINS,support

HOST_DL='/apex/com.android.runtime/lib64/bionic/libdl.so'
HOST_DL_SHA='7ba21006647292d7c51d4447ec336850f260e6b096a906b3c48cf44343e6f094'
PROXY_DL='/system/lib64/arm64/nb/libdl.so'
PROXY_C='/system/lib64/arm64/nb/libc.so'
ART='/apex/com.android.art/lib64/libart.so'
ART_SHA='6e390324e42eec50ce04e723c7f47ef4533d061d809da4e310041e08f26ea44c'
SLOTS=dict(malloc=0x1c72ba8,free=0x1c72bb0,pthread_mutex_lock=0x1c72de0,
    pthread_mutex_unlock=0x1c72df8,pthread_cond_signal=0x1c72e68,pthread_mutex_trylock=0x1c731b8)
_IMAGES={}


class PinnedElf(Elf):
    """Cache only pure queries of an immutable, completely verified byte image."""
    def __init__(self,raw,machine):
        super().__init__(raw,machine=machine);self._exports={};self._pointers={}

    def exports(self,names):
        key=tuple(sorted(names))
        if key not in self._exports:self._exports[key]=super().exports(set(key))
        return {name:dict(pin) for name,pin in self._exports[key].items()}

    def relative_pointer(self,va):
        if va not in self._pointers:self._pointers[va]=super().relative_pointer(va)
        return self._pointers[va]


def image(path,expected,machine=183):
    path=Path(path)
    if not 64<=path.stat().st_size<=128*1024*1024:raise ValueError('unbounded system ELF')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('MuMu system ELF changed: '+str(path))
    key=(str(path),expected,machine)
    cached=_IMAGES.get(key)
    if cached is not None and cached.raw==raw:return cached
    parsed=PinnedElf(raw,machine)
    # Bounded cache of system files only. Every call above rereads and hashes
    # the current bytes; no process address or memory result is cached.
    if len(_IMAGES)>=8 or sum(len(e.raw) for e in _IMAGES.values())+len(raw)>192*1024*1024:_IMAGES.clear()
    _IMAGES[key]=parsed
    return parsed


def bind_exports(session,path,elf,names,anchor=None):
    base=load_bias(session.verify().splitlines(),path,elf,anchor=anchor)
    if session.read(base,64)!=elf.raw[:64]:raise ValueError('MuMu ELF header differs')
    exports={};pins=elf.exports(set(names))
    values=session.read_many([(base+int(pin['va'],0),pin['size']) for pin in pins.values()])
    for (name,pin),raw in zip(pins.items(),values):
        address=base+int(pin['va'],0)
        if hashlib.sha256(raw).hexdigest()!=pin['sha256']:
            raise ValueError('MuMu mapped export differs: '+name)
        exports[name]=dict(pin,address=hex(address))
    return base,exports


def resolve_loader(session):
    if not enabled() or session.identity.get('native_transport')!='mumu-nativebridge-v1':raise ValueError('explicit MuMu identity required')
    dl=image(PROXY_DL,PINS[PROXY_DL]);pins=dl.exports({'dlopen','dlclose','dlerror'})
    base,exports=bind_exports(session,PROXY_DL,dl,pins,anchor=(int(pins['dlopen']['va'],0),session.pointer(session.base+0x1c73138)))
    _,host=bind_exports(session,HOST_DL,image(HOST_DL,HOST_DL_SHA,62),{'dlopen','dlclose','dlerror'})
    libc=image(PROXY_C,PINS[PROXY_C]);cpins=libc.exports(set(SLOTS))
    libc_base,cexports=bind_exports(session,PROXY_C,libc,cpins,anchor=(int(cpins['malloc']['va'],0),session.pointer(session.base+SLOTS['malloc'])))
    for (name,slot),raw in zip(SLOTS.items(),session.read_many([(session.base+slot,8) for slot in SLOTS.values()])):
        if struct.unpack('<Q',raw)[0]&0x00ffffffffffffff!=int(cexports[name]['address'],0):raise ValueError('MuMu game import changed: '+name)
    value=dict(identity=session.identity,library=PROXY_DL,library_sha256=PINS[PROXY_DL],base=hex(base),exports=exports,
        libc_library=PROXY_C,libc_library_sha256=PINS[PROXY_C],libc_base=hex(libc_base),libc_exports=cexports,
        mumu_bridge=dict(host_loader_exports=host),native_transport='mumu-nativebridge-v1')
    return value,dict(schema=1,native_transport='mumu-nativebridge-v1',guest_loader_verified=True,
        host_loader_verified=True,game_libc_imports_verified=True,native_calls=False,game_memory_written=False)


def bound_imports(session):
    if not enabled():raise ValueError('MuMu translation required')
    elf=image(PROXY_C,PINS[PROXY_C]);pins=elf.exports(set(SLOTS))
    _,exports=bind_exports(session,PROXY_C,elf,pins,anchor=(int(pins['malloc']['va'],0),session.pointer(session.base+SLOTS['malloc'])))
    result={}
    for (name,slot),raw in zip(SLOTS.items(),session.read_many([(session.base+slot,8) for slot in SLOTS.values()])):
        result[name]=struct.unpack('<Q',raw)[0]&0x00ffffffffffffff
        if result[name]!=int(exports[name]['address'],0):raise ValueError('MuMu import differs: '+name)
    return result


def borrowed_bindings(session):
    if not enabled():raise ValueError('MuMu translation required')
    result={}
    for key,path,sha,name in (
        ('bridge','/system/lib64/libnb.so',PINS['/system/lib64/libnb.so'],'NativeBridgeItf'),
        ('state','/apex/com.android.art/lib64/libnativebridge.so',PINS['/apex/com.android.art/lib64/libnativebridge.so'],'NativeBridgeInitialized'),
        ('vm',ART,ART_SHA,'JNI_GetCreatedJavaVMs')):
        elf=image(path,sha,62)
        base=load_bias(session.verify().splitlines(),path,elf)
        pin=elf.exports({name})[name];va=int(pin['va'],0);address=base+va
        if key=='bridge':
            if struct.unpack('<I',session.read(address,4))[0]!=6:raise ValueError('NativeBridge version changed')
            for offset in (24,72,96,112):
                target=elf.relative_pointer(va+offset)
                if session.raw_pointer(address+offset)!=base+target or session.read(base+target,32)!=elf.at(target,32):
                    raise ValueError('NativeBridge callback differs')
        elif hashlib.sha256(session.read(address,pin['size'])).hexdigest()!=pin['sha256']:
            raise ValueError('MuMu ART API changed')
        result[key]=address
    return result


def helper_profile():
    directory=support()/'helpers';profile=json.loads((directory/'profile.json').read_text())
    binaries=[]
    for key,machine in (('host',62),('guest',183)):
        raw=(directory/('librr_mumu_'+key+'.so')).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=profile[key+'_sha256']:raise ValueError('owned MuMu helper differs: '+key)
        elf=Elf(raw,machine=machine)
        if key=='host' and elf.exports(set(profile['host_exports']))!=profile['host_exports']:
            raise ValueError('owned MuMu helper export manifest differs')
        binaries.append(raw)
    destination=Path('/data/local/tmp')/('royale_replay_android_mumu_'+hashlib.sha256(b''.join(binaries)).hexdigest()[:20])
    for key in ('host','guest'):profile[key+'_device_path']=str(destination/('librr_mumu_'+key+'.so'))
    return profile


def publish_helpers(session):
    if not enabled():raise ValueError('MuMu translation required')
    profile=helper_profile();status=(session.proc/'status').read_text().splitlines()
    gid=int(next(row for row in status if row.startswith('Gid:')).split()[1])
    if not 10000<=gid<200000:raise ValueError('unexpected game group for owned helpers')
    directory=Path(profile['host_device_path']).parent
    if not directory.exists():
        directory.mkdir(mode=0o700);os.chown(directory,0,gid);os.chmod(directory,0o750)
    info=directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_gid!=gid or stat.S_IMODE(info.st_mode)!=0o750:
        raise ValueError('owned helper directory identity differs')
    for key in ('host','guest'):
        path=Path(profile[key+'_device_path'])
        if not path.exists():
            raw=(support()/'helpers'/path.name).read_bytes()
            with path.open('xb') as stream:stream.write(raw)
            os.chown(path,0,gid);os.chmod(path,0o640)
        info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_gid!=gid or stat.S_IMODE(info.st_mode)!=0o640:
            raise ValueError('owned helper permissions differ')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=profile[key+'_sha256']:raise ValueError('published helper differs')
    session.verify();return profile


def component_code_ranges(session,component):
    """Only the immutable, hash-bound component's ELF executable segments."""
    if not enabled() or session.identity.get('native_transport')!='mumu-nativebridge-v1':raise ValueError('MuMu component identity required')
    path=component['device_path']
    if not re.fullmatch(r'/data/local/tmp/royale-phone-[0-9a-f]{32}/libphone_replay_(bootstrap|scene)\.so',path):raise ValueError('not an owned MuMu component')
    info=Path(path).lstat();parent=Path(path).parent.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or stat.S_IMODE(info.st_mode)!=0o640 or not stat.S_ISDIR(parent.st_mode) or parent.st_uid!=0 or stat.S_IMODE(parent.st_mode)!=0o750:
        raise ValueError('MuMu component ownership differs')
    if not 64<=info.st_size<=16*1024*1024:raise ValueError('MuMu component size differs')
    raw=Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=component['sha256']:raise ValueError('MuMu component hash differs')
    elf=Elf(raw);base=load_bias(session.verify().splitlines(),path,elf)
    exports=elf.exports(set(component['exports']))
    if exports!=component['exports']:raise ValueError('MuMu component export contract differs')
    # One bounded read transaction, same header/export bytes and per-range limits.
    # read_many verifies process/mapping identity before AND after the whole batch.
    loaded=session.read_many([(base,64)]+[(base+int(pin['va'],0),pin['size']) for pin in exports.values()])
    if loaded[0]!=raw[:64]:raise ValueError('MuMu component header differs')
    for pin,actual in zip(exports.values(),loaded[1:]):
        if hashlib.sha256(actual).hexdigest()!=pin['sha256']:
            raise ValueError('MuMu loaded component export differs')
    ranges=[(base+p[3],base+p[3]+p[5]) for p in elf.programs if p[0]==1 and p[1]&1 and p[5]]
    if not ranges:raise ValueError('MuMu component has no code segments')
    return ranges
