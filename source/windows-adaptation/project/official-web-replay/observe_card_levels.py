"""Read only the requested source cards' public native level metadata."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from client_session import ReadOnlySession


# Tencent 38.4.2, libg SHA256 c6b2482a... (full hash enforced by the session).
# Spirit Empress is a concrete derived card definition, not an ordinary card
# with its type check disabled. Its inherited +0x100 getter is still exactly
# ldr x0,[x0,#0xa0]; ret, and points to the SAME validated level-source type.
STANDARD_DEFINITION_TABLE = 0x1c0be40
SPIRIT_EMPRESS_ID = 28000025
SPIRIT_EMPRESS_TABLE = 0x1bf4420
LEVEL_SOURCE_TABLE = 0x1c0a098
LEVEL_GETTER = 0x10cc890


def definition_table(data_id):
    return SPIRIT_EMPRESS_TABLE if data_id == SPIRIT_EMPRESS_ID else STANDARD_DEFINITION_TABLE


def main():
    p=argparse.ArgumentParser()
    for name in ('observation','source','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();identity=json.loads(a.observation.read_text(encoding="utf-8"))['identity']
    source=json.loads(a.source.read_text(encoding="utf-8"));s=ReadOnlySession(identity);retained=[]
    def fixed(address,size):
        pieces=[]
        for offset in range(0,size,0x1000):
            raw=s.read(address+offset,min(0x1000,size-offset))
            retained.append((address+offset,raw));pieces.append(raw)
        return b''.join(pieces)
    def ptr(address):return struct.unpack('<Q',fixed(address,8))[0]&0x00ffffffffffffff
    root=ptr(s.base+0x1d34ae0);services=ptr(root+0x20);catalog=ptr(services+0x38)
    if not catalog:raise ValueError('游戏卡牌目录尚未加载，请完成登录并进入大厅后重新准备')
    if ptr(catalog)!=s.base+0x1c04150:
        from device_catalog_diagnostic import save
        needed={c['base_data_id'] for d in source['decks'] for c in d['cards']}|{SPIRIT_EMPRESS_ID}
        save(s,services,needed,a.output.with_name('catalog-update-diagnostic.json'))
        raise ValueError('card catalog changed; read-only update evidence retained')
    entries=ptr(catalog+0xb8);count=struct.unpack('<i',fixed(catalog+0xc4,4))[0]
    if not 138<=count<=1024:raise ValueError('card catalog bounds changed')
    array=struct.unpack('<'+str(count)+'Q',fixed(entries,count*8))
    needed={c['base_data_id'] for d in source['decks'] for c in d['cards']}
    if None in needed:raise ValueError('source card IDs unresolved')
    def batch(ranges):
        raw=s.read_many(ranges)
        retained.extend((address,data) for (address,_),data in zip(ranges,raw))
        return raw
    # The historical version launched an ADB subprocess for every catalog ID,
    # every vtable slot and every reread. Preserve all checks, batch the I/O.
    ids=batch([(definition+0x40,4) for definition in array])
    selected=[];seen=set()
    for definition,raw in zip(array,ids):
        data_id=struct.unpack('<i',raw)[0]
        if data_id not in needed:continue
        if data_id in seen:raise ValueError('ambiguous card definition')
        seen.add(data_id);selected.append((definition,data_id))
    if seen!=needed:raise ValueError('source cards absent from native catalog')
    tables={definition_table(data_id) for _,data_id in selected}
    slots=[(s.base+table+0x100,LEVEL_GETTER) for table in sorted(tables)]
    slots.extend(((s.base+LEVEL_SOURCE_TABLE+0x118,0x10b1030),
                  (s.base+LEVEL_SOURCE_TABLE+0x120,0x10b1038)))
    for raw,(_,va) in zip(batch([(address,8) for address,_ in slots]),slots):
        if struct.unpack('<Q',raw)[0]&0x00ffffffffffffff!=s.base+va:raise ValueError('card level callback changed')
    if SPIRIT_EMPRESS_ID in needed:
        # Pin the inherited getter and both field getters as well as the slots.
        # These are byte observations, never calls into the client.
        getter_bytes=((LEVEL_GETTER,bytes.fromhex('005040f9c0035fd6')),
                      (0x10b1030,bytes.fromhex('003042b9c0035fd6')),
                      (0x10b1038,bytes.fromhex('003442b9c0035fd6')))
        for raw,(_,expected) in zip(batch([(s.base+va,len(expected)) for va,expected in getter_bytes]),getter_bytes):
            if raw!=expected:raise ValueError('Spirit Empress level getter code changed')
    headers=batch([(address,size) for definition,_ in selected for address,size in ((definition,8),(definition+0xa0,8))])
    levels=[]
    for index,(_,data_id) in enumerate(selected):
        table,level_source=(struct.unpack('<Q',raw)[0]&0x00ffffffffffffff for raw in headers[index*2:index*2+2])
        if table!=s.base+definition_table(data_id):raise ValueError('card definition type changed: '+str(data_id))
        levels.append((data_id,level_source))
    values=batch([(address,size) for _,level in levels for address,size in ((level,8),(level+0x230,8))])
    found={}
    for index,(data_id,_) in enumerate(levels):
        table=struct.unpack('<Q',values[index*2])[0]&0x00ffffffffffffff
        if table!=s.base+LEVEL_SOURCE_TABLE:raise ValueError('level source type changed: '+str(data_id))
        offset,ceiling=struct.unpack('<ii',values[index*2+1])
        if not 0<=offset<=15:raise ValueError('level offset outside supported range')
        found[data_id]=dict(data_id=data_id,display_offset=offset+1,offset_A=offset,ceiling_B=ceiling,
                            definition_type='spirit-empress' if data_id==SPIRIT_EMPRESS_ID else 'standard',
                            definition_table_va=hex(definition_table(data_id)))
    if set(found)!=needed:raise ValueError('source cards absent from native catalog')
    for (_,raw),again in zip(retained,s.read_many([(address,len(raw)) for address,raw in retained])):
        if again!=raw:raise ValueError('public catalog generation changed')
    s.verify()
    report=dict(identity=identity,cards=list(found.values()),source_sha256=source['source_sha256'],
                native_calls=False,game_memory_written=False,network_settings_changed=False,
                source_manifest_sha256=hashlib.sha256(a.source.read_bytes()).hexdigest())
    with a.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2)
    print(json.dumps(report['cards']))


if __name__=='__main__':main()
