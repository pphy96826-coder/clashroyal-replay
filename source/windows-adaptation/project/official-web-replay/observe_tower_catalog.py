"""Bounded read-only evidence for all active native ladder tower troops."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from client_session import ReadOnlySession
from tower_profiles import TOWERS

MASK=0x00ffffffffffffff


def observe(s):
    retained=[]
    def read(address,size):
        raw=s.read(address,size);retained.append((address,raw));return raw
    def ptr(address):return struct.unpack('<Q',read(address,8))[0]&MASK
    def name(address):
        raw=read(address+0x28,16);size=struct.unpack_from('<i',raw,4)[0]
        if not 0<size<=64:raise ValueError('invalid bounded public tower name')
        text=raw[8:8+size] if size<8 else read(struct.unpack_from('<Q',raw,8)[0]&MASK,size)
        if any(c<32 or c>=127 for c in text):raise ValueError('invalid public tower name bytes')
        return text.decode('ascii')
    root=ptr(s.base+0x1d34ae0);services=ptr(root+0x20);catalog=ptr(services+0x548)
    header=read(catalog,0x88)
    if struct.unpack_from('<Q',header)[0]&MASK!=s.base+0x1c04c18 or struct.unpack_from('<i',header,0x84)[0]!=169:
        raise ValueError('native SupportCard catalog differs')
    if struct.unpack_from('<Q',header,0x78)[0]&MASK!=services:raise ValueError('tower catalog owner differs')
    array,capacity,count=struct.unpack_from('<Qii',header,0x30)
    if not 4<=count<=capacity<=32:raise ValueError('tower catalog bounds differ')
    pointers=struct.unpack('<'+str(count)+'Q',read(array&MASK,count*8))
    rows=[]
    for key,expected in TOWERS.items():
        matches=[]
        for address in pointers:
            if struct.unpack('<i',read(address+0x40,4))[0]==expected['support_id']:matches.append(address&MASK)
        if len(matches)!=1:raise ValueError('tower record not unique: '+key)
        record=matches[0]
        if ptr(record)!=s.base+0x1c0c800 or ptr(record+0x10)!=catalog or name(record)!=expected['name']:
            raise ValueError('tower definition differs: '+key)
        rarity=ptr(record+0xa0);group=ptr(record+0xa8)
        if ptr(rarity)!=s.base+0x1c0ca28 or name(group)!=expected['name']:
            raise ValueError('tower rarity or spawn group differs')
        # Getter118 reads relative level at70; count is read from native data.
        rarity_header=read(rarity+0x6c,8)
        level_count=struct.unpack_from('<i',rarity_header,0)[0]
        relative=struct.unpack_from('<i',rarity_header,4)[0]
        if not 1<=level_count<=16 or not 0<=relative<=15:raise ValueError('invalid tower rarity')
        spawn=read(group+0x90,17);entries,cap,n=struct.unpack_from('<Qii',spawn)
        if n!=3 or not n<=cap<=32 or spawn[16]!=1:raise ValueError('not a three-tower mirrored1v1 group')
        items=struct.unpack('<3Q',read(entries&MASK,24));spawns=[]
        for item in items:
            definition,x,y,side=struct.unpack('<Qiii',read(item+8,20));definition&=MASK
            data_id=struct.unpack('<i',read(definition+0x40,4))[0];kind=name(definition)
            if kind not in (expected['king_character'],expected['character']) or not 0<=x<=36 or not 0<=y<=64 or side!=-1:
                raise ValueError('tower spawn is outside the expected ladder layout')
            spawns.append(dict(data_id=data_id,name=kind,grid_x=x,grid_y=y,side_filter=side))
        if sum(e['name']==expected['king_character'] for e in spawns)!=1:raise ValueError('tower group king count differs')
        rows.append(dict(card_key=key,support_id=expected['support_id'],name=expected['name'],
                         relative_level=relative,level_count=level_count,spawn_entries=spawns))
    if s.read_many([(a,len(raw)) for a,raw in retained])!=[raw for _,raw in retained]:
        raise ValueError('public tower catalog changed during observation')
    s.verify();return rows


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--observation',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    identity=json.loads(args.observation.read_text())['identity'];s=ReadOnlySession(identity)
    try:
        rows=observe(s)
    except ValueError:
        from device_catalog_diagnostic import capture_towers
        try:
            def ptr(address):return struct.unpack('<Q',s.read(address,8))[0]&MASK
            root=ptr(s.base+0x1d34ae0);services=ptr(root+0x20)
            evidence=capture_towers(s,services,{row['support_id'] for row in TOWERS.values()})
        except (ValueError,OSError,struct.error) as error:
            evidence=dict(state='observation_incomplete',error=str(error)[:300],native_calls=False,
                          game_memory_written=False,compatibility_approved=False)
        with args.output.with_name('tower-update-diagnostic.json').open('x') as stream:json.dump(evidence,stream,indent=2)
        raise
    result=dict(identity=identity,towers=rows,native_calls=False,game_memory_written=False,
                network_settings_changed=False,observer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    with args.output.open('x') as stream:json.dump(result,stream,ensure_ascii=False,indent=2)
    print(json.dumps(rows,ensure_ascii=False))


if __name__=='__main__':main()
