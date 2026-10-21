"""Fresh, phone-local runtime inputs. Only reads installed public resources."""
import json
from pathlib import Path
import struct
import zipfile

from device_session import CONTRACT, ReadOnlySession, start_time
from elf_contract import Elf
from device_loader import LoaderResolutionError, resolve_loader
from local_assets import generate


class SceneSnapshotChanged(ValueError):
    """A read-only scene observation raced a controller/manager transition."""


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
        if session.pointer(controller)!=table:raise SceneSnapshotChanged('controller changed during observation')
    if not manager or session.pointer(manager+0x28)!=controller or session.pointer(base+0x1d46bd0)!=manager:
        raise SceneSnapshotChanged('scene manager changed during observation')
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
    try:
        if identity.get('native_transport')=='mumu-nativebridge-v1':
            from mumu_runtime import resolve_loader as resolve_mumu_loader
            loader,loader_diagnostic=resolve_mumu_loader(session)
        else:loader,loader_diagnostic=resolve_loader(session,Elf)
    except LoaderResolutionError as exc:
        with (destination/'loader-diagnostic.json').open('x') as stream:
            json.dump(exc.diagnostic,stream,indent=2)
        raise
    with (destination/'loader-diagnostic.json').open('x') as stream:
        json.dump(loader_diagnostic,stream,indent=2)
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
