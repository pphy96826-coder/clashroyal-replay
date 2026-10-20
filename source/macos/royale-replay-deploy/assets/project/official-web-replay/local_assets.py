"""Regenerate the two small map fixtures from the user's own matching APK."""
import csv
import hashlib
import io
import json
import lzma
import struct


def decode(raw):
    if not 9<=len(raw)<=1048576:raise ValueError('invalid compressed map size')
    size=struct.unpack_from('<I',raw,5)[0]
    if not 0<size<=1048576:raise ValueError('invalid plain map size')
    decoder=lzma.LZMADecompressor(lzma.FORMAT_ALONE,memlimit=67108864)
    plain=decoder.decompress(raw[:5]+struct.pack('<Q',size)+raw[9:],max_length=size+1)
    if len(plain)!=size or b'\0' in plain:raise ValueError('invalid decoded asset')
    plain.decode('ascii');return plain


def generate(archive,workspace,expected):
    names=('locations/dragon_arena.csv','tilemaps/tilemap.csv');contents=[]
    for name in names:
        entry=archive.getinfo('assets/'+name)
        if entry.file_size>1048576:raise ValueError('asset too large')
        plain=decode(archive.read(entry))
        if hashlib.sha256(plain).hexdigest()!=expected[name]:raise ValueError('installed map resource differs')
        contents.append(plain)
    rows=list(csv.reader(io.StringIO(contents[1].decode('ascii')),strict=True))
    starts=[i for i,r in enumerate(rows) if r and r[0]=='Map']
    if len(starts)!=1:raise ValueError('unique map table required')
    start=starts[0];width=len(rows[start+1])-1
    if width!=36 or rows[start+2]!=['']+['int']*width:raise ValueError('map shape differs')
    grid=[]
    for row in rows[start+3:]:
        if row and row[0]:break
        if not row:continue
        if len(row)!=width+1:raise ValueError('ragged map')
        values=[int(value) if value else 0 for value in row[1:]]
        if any(not 0<=v<=1023 for v in values):raise ValueError('invalid map bits')
        grid.extend(values)
    if len(grid)!=36*64:raise ValueError('map height differs')
    rows=list(csv.reader(io.StringIO(contents[0].decode('ascii')),strict=True));objects=[];inside=False;name=None
    for row in rows:
        if row and row[0]=='Objects':inside=True;continue
        if inside and row and row[0]:break
        if not inside or len(row)<4:continue
        if row[1] and not row[1].isdigit():name=row[1]
        if name and row[2].lstrip('-').isdigit() and row[3].lstrip('-').isdigit():objects.append((name,int(row[2]),int(row[3])))
    if len(objects)!=10:raise ValueError('unexpected arena decoration layout')
    lines=['// Generated locally from the receiving user\'s APK.','#pragma once']
    for i,plain in enumerate(contents):
        lines+=['static const char asset_'+str(i)+'[]={'+','.join(map(str,plain))+',0};',
                'static const int asset_'+str(i)+'_size='+str(len(plain))+';']
    lines+=['static const int expected_cells[]={'+','.join(map(str,grid))+'};','static const unsigned map_width=36,map_height=64;']
    paths=[(workspace/'offline-private-map/build/assets.h','\n'.join(lines)+'\n'),
           (workspace/'offline-private-layout/build/objects.h','#pragma once\nstatic constexpr private_layout::ExpectedObject expected_objects[]={'+
            ','.join('{'+json.dumps(n)+','+str(x)+','+str(y)+'}' for n,x,y in objects)+
            '};\nstatic constexpr unsigned expected_object_count=sizeof(expected_objects)/sizeof(expected_objects[0]);\n')]
    for path,text in paths:
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('x') as f:f.write(text)
    return dict(map_width=36,map_height=64,decorations=len(objects),generated_from_local_apk=True)
