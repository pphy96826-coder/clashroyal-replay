"""Read-only public catalog evidence when a version's type check fails.

No native functions are called. Observed tables/getters are candidates, never
permission to bypass the failing observer or enable an unknown client.
"""
import json
import struct

MASK=0x00ffffffffffffff


def simple_getter(raw):
    if len(raw)!=8:return None
    word,ret=struct.unpack('<II',raw)
    if ret!=0xd65f03c0:return None
    if word&0xffc003ff==0xf9400000:
        return dict(kind='pointer',field_offset=hex(((word>>10)&0xfff)*8))
    if word&0xffc003ff==0xb9400000:
        return dict(kind='integer',field_offset=hex(((word>>10)&0xfff)*4))
    return None


def capture(session,services,needed):
    def pointer(address):return struct.unpack('<Q',session.read(address,8))[0]&MASK
    def relative(pointer):return hex(pointer-session.base)
    def blocks(address,n):
        return b''.join(session.read(address+i,min(4096,n-i)) for i in range(0,n,4096))
    def getters(table):
        # Small, explicitly bounded neighborhood of the known level getters.
        raw=session.read(table+0xf8,0x40);result=[]
        for i,value in enumerate(struct.unpack('<8Q',raw)):
            method=value&MASK
            if not session.base<=method<method+8<=session.end:continue
            info=simple_getter(session.read(method,8))
            if info:result.append(dict(slot=hex(0xf8+i*8),method_va=relative(method),**info))
        return result
    report=dict(schema='royale-replay.public-catalog-update-evidence.v1',
                native_calls=False,game_memory_written=False,compatibility_approved=False,
                library_sha256=session.identity['library_sha256'])
    catalog=pointer(services+0x38)
    if not catalog:return dict(report,state='catalog_not_ready')
    header=session.read(catalog,0xc8)
    table=struct.unpack_from('<Q',header)[0]&MASK
    entries=struct.unpack_from('<Q',header,0xb8)[0]&MASK
    count=struct.unpack_from('<i',header,0xc4)[0]
    report.update(state='observed_candidates',catalog_table_va=relative(table),catalog_count=count)
    if not entries or not 138<=count<=1024:
        return dict(report,state='catalog_shape_changed')
    definitions=struct.unpack('<'+str(count)+'Q',blocks(entries,count*8))
    selected=[]
    for address in definitions:
        address&=MASK
        data_id=struct.unpack('<i',session.read(address+0x40,4))[0]
        if data_id not in needed:continue
        definition_table=pointer(address);level=pointer(address+0xa0)
        row=dict(data_id=data_id,definition_table_va=relative(definition_table),
                 definition_getters=getters(definition_table))
        if level:
            level_table=pointer(level)
            row.update(level_table_va=relative(level_table),level_getters=getters(level_table))
            # Values at the historical fields are evidence, not accepted levels.
            row['historical_level_fields']=list(struct.unpack('<ii',session.read(level+0x230,8)))
        selected.append(row)
    session.verify()
    report['cards']=selected;report['generation_verified']=True
    return report


def save(session,services,needed,path):
    try:
        report=capture(session,services,needed)
    except (ValueError,OSError,struct.error) as error:
        report=dict(schema='royale-replay.public-catalog-update-evidence.v1',
                    state='observation_incomplete',error=str(error)[:300],
                    native_calls=False,game_memory_written=False,compatibility_approved=False)
    with path.open('x') as stream:json.dump(report,stream,indent=2)
    return report


def capture_towers(session,services,needed):
    def pointer(address):return struct.unpack('<Q',session.read(address,8))[0]&MASK
    def relative(value):return hex(value-session.base)
    catalog=pointer(services+0x548)
    report=dict(schema='royale-replay.public-tower-update-evidence.v1',native_calls=False,
                game_memory_written=False,compatibility_approved=False)
    if not catalog:return dict(report,state='catalog_not_ready')
    header=session.read(catalog,0x88)
    report['catalog_table_va']=relative(struct.unpack_from('<Q',header)[0]&MASK)
    report['table_id']=struct.unpack_from('<i',header,0x84)[0]
    array,capacity,count=struct.unpack_from('<Qii',header,0x30)
    if not 4<=count<=capacity<=32:return dict(report,state='catalog_shape_changed')
    addresses=struct.unpack('<'+str(count)+'Q',session.read(array&MASK,count*8))
    rows=[]
    for address in addresses:
        address&=MASK
        data_id=struct.unpack('<i',session.read(address+0x40,4))[0]
        if data_id not in needed:continue
        rarity=pointer(address+0xa0);group=pointer(address+0xa8)
        rows.append(dict(data_id=data_id,definition_table_va=relative(pointer(address)),
                         owner_matches=pointer(address+0x10)==catalog,
                         rarity_table_va=relative(pointer(rarity)) if rarity else None,
                         group_table_va=relative(pointer(group)) if group else None))
    session.verify();report.update(state='observed_candidates',rows=rows)
    return report
