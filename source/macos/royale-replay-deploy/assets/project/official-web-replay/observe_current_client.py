"""Fresh identity and typed public Location-cache readiness; read only."""
import argparse,copy,hashlib,json,struct,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'vendor'))
from client_session import ReadOnlySession,ensure_current_device_binding

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    from portable_config import runtime_profile
    old=runtime_profile()
    device=ensure_current_device_binding()
    adb=['adb','-s',device['serial']]
    pidtext=subprocess.check_output(adb+['shell','pidof com.tencent.tmgp.supercell.clashroyale'],text=True,timeout=10).split()
    if len(pidtext)!=1:raise ValueError('one existing official client required')
    pid=int(pidtext[0]);stat=subprocess.check_output(adb+['shell',f'cat /proc/{pid}/stat'],text=True,timeout=10)
    maps=subprocess.check_output(adb+['shell',f'cat /proc/{pid}/maps'],text=True,timeout=10)
    apkrows=subprocess.check_output(adb+['shell','pm','path',old['package']],text=True,timeout=10).splitlines()
    apks=[v.removeprefix('package:') for v in apkrows if v.endswith('/base.apk')]
    if len(apks)!=1:raise ValueError('one installed official base APK required')
    matches=[line for line in maps.splitlines() if len(line.split())>=6 and line.split()[1]=='r-xp'
             and int(line.split()[2],16)==old['mapping_file_offset'] and line.split()[-1]==apks[0]]
    if len(matches)!=1:raise ValueError('installed APK mapping changed; require new binary identification')
    lo,hi=(int(x,16) for x in matches[0].split()[0].split('-'))
    if hi-lo!=old['executable_span']:raise ValueError('library extent changed')
    identity={k:old[k] for k in ('library_bytes','library_sha256','jni_exports')};identity.update(apk=apks[0],serial=device['serial'],device_binding=device,pid=pid,base=hex(lo),executable_end=hex(hi),mapping=matches[0],
        process_start_time=stat[stat.rfind(')')+2:].split()[19])
    s=ReadOnlySession(identity);pins=[]
    def fixed(name,address,size):
        raw=s.read(address,size)
        if s.read(address,size)!=raw:raise ValueError('unstable '+name)
        pins.append({'name':name,'address':hex(address),'size':size,'raw_hex':raw.hex(),'sha256':hashlib.sha256(raw).hexdigest()})
        return raw
    def ptr(name,address):return struct.unpack('<Q',fixed(name,address,8))[0]
    root=ptr('services-root',s.base+0x1d34ae0);services=ptr('services',root+0x20)
    registry=ptr('location-registry',services+0x78)
    header=fixed('location-registry-header',registry,0x88)
    if struct.unpack_from('<i',header,0x84)[0]!=15:raise ValueError('not category15 Location')
    entries,capacity,count=struct.unpack_from('<Qii',header,0x30)
    if not 61<count<=capacity<=1024:raise ValueError('Location registry not ready')
    location=ptr('dragon-location',entries+61*8)
    row=fixed('dragon-location-header',location,0x50)
    if struct.unpack_from('<I',row,0x40)[0]!=15000061 or struct.unpack_from('<Q',row,0x10)[0]!=registry:
        raise ValueError('wrong Location definition')
    cache=fixed('location-layout-cache',services+0x13d8,16)
    array,cache_capacity,cache_count=struct.unpack('<Qii',cache)
    if not 0<=cache_count<=cache_capacity<=512:raise ValueError('invalid layout cache')
    layout=ptr('dragon-layout-cache-slot',array+61*8) if cache_count>61 else 0
    # The getter must still implement this typed cache, not guessed +field reads.
    fixed('location-layout-getter',s.base+0x1090a7c,0x34)
    worker=ptr('mainloop-handle',s.base+0x1d88820)
    tid=struct.unpack('<i',fixed('mainloop-tid',worker+0x10,4))[0] if worker else None
    if tid:
        wstat=subprocess.check_output(adb+['shell',f'cat /proc/{pid}/task/{tid}/stat'],text=True,timeout=10)
        worker_start=wstat[wstat.rfind(')')+2:].split()[19]
    else:worker_start=None
    manager=ptr('native-scene-manager',s.base+0x1d46bd0)
    scene_state={'manager':hex(manager)}
    if manager:
        controller=ptr('native-primary-controller',manager+0x28)
        scene_state['controller']=hex(controller)
        if controller:
            table=ptr('primary-controller-type',controller)
            scene_state['vtable_va']=hex((table&0x00ffffffffffffff)-s.base)
            if table==s.base+0x1bebd08:
                scene_state['kind']=struct.unpack('<i',fixed('controller-kind',controller+0x58,4))[0]
                scene_state['state']=struct.unpack('<i',fixed('controller-state',controller+0x30,4))[0]
                domain=ptr('controller-domain',controller+0x90)
                scene_state['domain']=hex(domain)
                if domain:
                    scene_state['domain_mode']=struct.unpack('<i',fixed('controller-domain-mode',domain+0x20,4))[0]
                    scene_state['battle_present']=bool(ptr('controller-battle',domain+0xa8))
    s.verify()
    doc={'identity':identity,'root_raw':hex(root),'services_raw':hex(services),'worker_handle':hex(worker),
        'adb_discovery':{'serial':device['serial'],'source':'existing Android1 settings; loopback only','auto_reconnect':True},
        'worker_tid':tid,'worker_start_time':worker_start,'location_id':15000061,'location':hex(location),
        'cache_count':cache_count,'location_layout':hex(layout),'native_loader_resource_ready':bool(layout),
        'scene_state':scene_state,'native_calls':False,'game_memory_written':False,'network_settings_changed':False,'pins':pins}
    with args.output.open('x') as f:json.dump(doc,f,indent=2)
    print(json.dumps({k:doc[k] for k in ('adb_discovery','worker_tid','cache_count','location_layout','native_loader_resource_ready','native_calls')}))

if __name__=='__main__':main()
