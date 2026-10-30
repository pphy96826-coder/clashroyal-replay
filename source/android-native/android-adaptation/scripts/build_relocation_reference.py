"""Build non-executable relocation fingerprints from the user's audited APK."""
import argparse,hashlib,json,struct,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def normalize(word):
 if word&0x7c000000==0x14000000:return word&0xfc000000 # B/BL
 if word&0x9f000000 in (0x10000000,0x90000000):return word&0x9f00001f # ADR/ADRP
 if word&0xff000010==0x54000000:return word&0xff00001f # B.cond
 if word&0x7e000000==0x34000000:return word&0xff00001f # CBZ/CBNZ
 if word&0x7e000000==0x36000000:return word&0xfff8001f # TBZ/TBNZ
 if word&0x3b000000==0x18000000:return word&0xff00001f # literal loads
 return word

def segments(data):
 if data[:6]!=b'\x7fELF\x02\x01' or struct.unpack_from('<H',data,18)[0]!=183:raise ValueError('ARM64 ELF required')
 off=struct.unpack_from('<Q',data,32)[0];size,count=struct.unpack_from('<HH',data,54)
 if size!=56 or count>256 or off+size*count>len(data):raise ValueError('invalid program table')
 out=[]
 for i in range(count):
  typ,flags,fo,va,_,sz,_,_=struct.unpack_from('<IIQQQQQQ',data,off+i*size)
  if typ==1 and flags&1:
   if fo+sz>len(data) or sz<32 or fo%4:raise ValueError('invalid executable segment')
   out.append((fo,va,sz))
 return out

def build(apk,contract):
 with zipfile.ZipFile(apk) as z:
  entry=z.getinfo('lib/arm64-v8a/libg.so')
  if not 64<=entry.file_size<=64*1024*1024:raise ValueError('library limit')
  data=z.read(entry)
 if hashlib.sha256(data).hexdigest()!=contract['library_sha256']:raise ValueError('reference is not audited binary')
 rows=['replay-relocation-v2 '+contract['library_sha256']]
 known={int(pin['va'],0) for pin in contract['pins']}
 for pin in contract['pins']:
  va=int(pin['va'],0);raw=None
  for off,start,n in segments(data):
   if start<=va and va+32<=start+n:raw=data[off+va-start:off+va-start+32];break
  if raw is None or pin['size']!=32 or hashlib.sha256(raw).hexdigest()!=pin['file_sha256']:raise ValueError('reference pin mismatch')
  words=struct.unpack('<8I',raw);masked=struct.pack('<8I',*(normalize(w) for w in words))
  edges=[]
  for i,w in enumerate(words):
   if w&0x7c000000==0x14000000:
    delta=w&0x3ffffff
    if delta&(1<<25):delta-=1<<26
    target=va+i*4+delta*4
    if target in known:edges.append(f"{i*4}:{target:x}")
  rows.append(f"{va:x} {hashlib.sha256(masked).hexdigest()} {normalize(words[0]):08x} {','.join(edges) or '-'}")
 return '\n'.join(rows)+'\n'
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('apk',type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
 a.output.write_text(build(a.apk,json.loads((ROOT/'profiles/native-code-contract.json').read_text())))
