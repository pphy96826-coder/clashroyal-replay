"""Fresh, phone-local runtime inputs. Only reads installed public resources."""
import hashlib
import json
from pathlib import Path
import struct
import zipfile

from device_session import CONTRACT, ReadOnlySession, start_time
from elf_contract import Elf
from local_assets import generate


def scene_state(identity):
    """Read only known controller layouts; a foreground Activity may be loading.

    Unknown controllers are not BattleControllers. In particular, never read
    their +0x90 as a Domain just because the game's Activity is resumed.
    """
    session=ReadOnlySession(identity);base=session.base
    manager=session.pointer(base+0x1d46bd0)
    controller=session.pointer(manager+0x28) if manager else 0
    state=dict(controller_present=bool(controller))
    if controller:
        table=session.pointer(controller)
        state['controller_vtable_va']=hex(table-base)
        if table==base+0x1bebd08:
            state['kind']=struct.unpack('<i',session.read(controller+0x58,4))[0]
            state['state']=struct.unpack('<i',session.read(controller+0x30,4))[0]
            domain=session.pointer(controller+0x90)
            state['domain_mode']=struct.unpack('<i',session.read(domain+0x20,4))[0] if domain else None
            state['battle_present']=bool(session.pointer(domain+0xa8)) if domain else False
            state['pending_request']=struct.unpack('<i',session.read(manager+0x3c,4))[0]
            state['auxiliary_present']=bool(session.pointer(manager+0x20))
        if session.pointer(controller)!=table:raise ValueError('controller changed during observation')
    if not manager or session.pointer(manager+0x28)!=controller or session.pointer(base+0x1d46bd0)!=manager:
        raise ValueError('scene manager changed during observation')
    session.verify()
    return state


def prepare(identity, destination):
    destination.mkdir(exist_ok=False, mode=0o700)
    with zipfile.ZipFile(identity['apk']) as archive:
        assets=generate(archive, destination, CONTRACT['map_asset_sha256'])
    session=ReadOnlySession(identity)
    base=session.base
    root=session.raw_pointer(base+0x1d34ae0)
    services=session.raw_pointer(root+0x20)
    worker=session.raw_pointer(base+0x1d88820)
    if not root or not services or not worker:
        raise ValueError('public runtime resource owner is not ready')
    tid=struct.unpack('<i',session.read(worker+0x10,4))[0]
    if not 0<tid<1<<22:raise ValueError('native worker is absent')
    task=Path('/proc')/str(session.pid)/'task'/str(tid)/'stat'
    worker_start=start_time(task.read_text())
    manager=session.pointer(base+0x1d46bd0)
    if not manager:raise ValueError('native scene manager is absent')
    controller=session.pointer(manager+0x28)
    state=dict(controller_present=bool(controller))
    if controller:
        table=session.pointer(controller)
        state['controller_vtable_va']=hex(table-base)
        if table==base+0x1bebd08:
            state['kind']=struct.unpack('<i',session.read(controller+0x58,4))[0]
            state['state']=struct.unpack('<i',session.read(controller+0x30,4))[0]
            domain=session.pointer(controller+0x90)
            state['domain_mode']=struct.unpack('<i',session.read(domain+0x20,4))[0] if domain else None
            state['battle_present']=bool(session.pointer(domain+0xa8)) if domain else False
            state['pending_request']=struct.unpack('<i',session.read(manager+0x3c,4))[0]
            state['auxiliary_present']=bool(session.pointer(manager+0x20))
    maps=session.verify().splitlines()
    loader_path=Path('/apex/com.android.runtime/lib64/bionic/libdl.so')
    raw=loader_path.read_bytes();elf=Elf(raw)
    bases=[int(line.split()[0].split('-')[0],16) for line in maps if len(line.split())>=6
           and line.split()[-1]==str(loader_path) and int(line.split()[2],16)==0]
    if len(bases)!=1:raise ValueError('system loader mapping is not unique')
    loader_base=bases[0];exports=elf.exports({'dlopen','dlclose','dlerror'})
    for pin in exports.values():
        address=loader_base+int(pin['va'],0)
        if hashlib.sha256(session.read(address,pin['size'])).hexdigest()!=pin['sha256']:
            raise ValueError('live loader differs from installed system library')
        pin['address']=hex(address)
    loader=dict(identity=identity,library=str(loader_path),library_sha256=hashlib.sha256(raw).hexdigest(),
                base=hex(loader_base),exports=exports)
    if (session.raw_pointer(base+0x1d34ae0)!=root or session.raw_pointer(root+0x20)!=services
            or session.raw_pointer(base+0x1d88820)!=worker or start_time(task.read_text())!=worker_start):
        raise ValueError('public resource or native worker generation changed')
    session.verify()
    result=dict(identity=identity,root_raw=hex(root),services_raw=hex(services),worker_handle=hex(worker),
                worker_tid=tid,worker_start_time=worker_start,scene_state=state,
                assets=assets,native_calls=False,game_memory_written=False,
                debugger_attached=False,processing_location='android',desktop_backend_used=False)
    for name,value in (('runtime-observation.json',result),('loader-profile.json',loader)):
        with (destination/name).open('x') as stream:json.dump(value,stream,indent=2)
    return result
