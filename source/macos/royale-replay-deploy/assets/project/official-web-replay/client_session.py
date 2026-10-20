"""Rebind the SAME Android1 after its loopback ADB port changes.

Keep historical capture tools unchanged. Reuse their exact read limits, APK/JNI
and process-generation checks in a private module whose serial is explicitly
bound to MuMu's existing instance1 configuration. Fresh observations reconnect
only that instance's configured loopback endpoint; never scan other ports.
"""
import importlib.util
import json
from pathlib import Path
import subprocess
import struct
from bounded_memory_reader import ensure_reader

ROOT=Path(__file__).resolve().parent
from portable_config import instance_dir,instance_name
INSTANCE=instance_dir()


def current_device_binding():
    settings=json.loads((INSTANCE/'setting/vm.json').read_text())
    port=settings['adbPort']
    name=settings['vmName']
    if name!=instance_name() or type(port) is not int or not 1024<=port<=65535:
        raise ValueError('existing Android1 device binding changed')
    return {'instance_dir':str(INSTANCE),'instance_name':name,'adb_port':port,'serial':'127.0.0.1:'+str(port)}


def validate_device_binding(identity):
    current=current_device_binding()
    if identity.get('device_binding')!=current or identity.get('serial')!=current['serial']:
        raise ValueError('stale or different emulator binding: observe existing Android1 again')
    return current


def ensure_current_device_binding():
    from adb_discovery import resolve_device
    return resolve_device(current_device_binding)


class ReadOnlySession:
    def __init__(self,identity):
        binding=validate_device_binding(identity)
        path=ROOT.parent/'vendor/inspect_registry.py'
        spec=importlib.util.spec_from_file_location('bound_android1_reader',path)
        reader=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reader)
        # This is an isolated reader module, not a mutation of the historical
        # source file, another task's module globals, or device/network config.
        reader.SERIAL=binding['serial']
        self._reader=reader
        self._session=reader.ReadOnlySession(identity)

    def __getattr__(self,name):
        return getattr(self._session,name)

    def verify(self):
        validate_device_binding(self._session.identity)
        return self._session.verify()

    def read_many(self, ranges):
        """Batch exact bounded reads; no persistent memory cache or new access.

        Same mapped-range, 4KiB per-read and 64KiB session budget as read().
        Only numeric validated addresses/PID enter the local ADB command.
        Callers retain their before/after generation and double-read checks.
        """
        validate_device_binding(self._session.identity)
        ranges=list(ranges)
        if len(ranges)>4096:raise ValueError('excessive batch range count')
        checked=[];used=self._session.used
        for address,size in ranges:
            if type(address) is not int:raise ValueError('integer address required')
            address=self._reader.checked_range(address,size,self._session.mappings,used)
            checked.append((address,size));used+=size
        self._session.used=used
        if not checked:return []
        if not getattr(self._session,'batch_reader',None):
            self._session.batch_reader=ensure_reader(self._session.adb)
        payload=struct.pack('<I',len(checked))+b''.join(struct.pack('<QI',address,size) for address,size in checked)
        raw=subprocess.check_output(self._session.adb+['shell','-T',self._session.batch_reader,
            str(self._session.pid),self._session.identity['process_start_time']],input=payload,timeout=10)
        if len(raw)!=sum(size for _,size in checked):raise RuntimeError('short bounded memory batch')
        result=[];offset=0
        for _,size in checked:
            result.append(raw[offset:offset+size]);offset+=size
        validate_device_binding(self._session.identity)
        return result
