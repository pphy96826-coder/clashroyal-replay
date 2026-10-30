"""Read-only ARM64 update comparison using unwind function boundaries.
Unique matches are candidates, never a runtime-compatibility authorization.
"""
import bisect,hashlib,json,struct,zipfile
from pathlib import Path
from build_relocation_reference import normalize,segments

def sections(data):
 offset=struct.unpack_from('<Q',data,40)[0];size,count,index=struct.unpack_from('<HHH',data,58)
 if size!=64 or count>8192 or index>=count or offset+size*count>len(data):raise ValueError('invalid ELF sections')
 records=[struct.unpack_from('<IIQQQQIIQQ',data,offset+i*size) for i in range(count)]
 names=records[index];strings=data[names[4]:names[4]+names[5]]
 out={}
 for row in records:
  name=strings[row[0]:].split(b'\0',1)[0].decode('ascii');out[name]=row
 return out

def normalized(data):
 words=list(struct.unpack('<'+'I'*(len(data)//4),data[:len(data)//4*4]));out=[];pages={}
 for i,w in enumerate(words):
  value=normalize(w)
  # Page offsets are relocations ONLY when this base was formed by a nearby ADRP.
  # Object member offsets loaded through other registers remain intact.
  pages={r:t for r,t in pages.items() if i-t<=4}
  rn=(w>>5)&31;rd=w&31
  if w&0x9f000000==0x90000000:pages[rd]=i
  elif w&0x7f000000==0x11000000 and rn in pages and not w&(1<<22):
   value=w&~(0xfff<<10);pages.pop(rd,None)
  elif w&0x3b000000==0x39000000 and rn in pages:
   value=w&~(0xfff<<10)
   if w&(1<<22):pages.pop(rd,None)
  elif w&0x7c000000==0x14000000 or w&0xff000010==0x54000000:pages.clear()
  else:pages.pop(rd,None)
  out.append(value)
 return struct.pack('<'+'I'*len(out),*out)

class Image:
 def __init__(self,apk):
  with zipfile.ZipFile(apk) as z:self.data=z.read('lib/arm64-v8a/libg.so')
  self.loads=segments(self.data);sec=sections(self.data);h=sec['.eh_frame_hdr'];hdr=self.data[h[4]:h[4]+h[5]]
  if hdr[:4]!=b'\x01\x1b\x03\x3b':raise ValueError('unsupported unwind table encoding')
  count=struct.unpack_from('<I',hdr,8)[0]
  if 12+count*8!=len(hdr):raise ValueError('invalid unwind table size')
  self.starts=[h[3]+struct.unpack_from('<i',hdr,12+i*8)[0] for i in range(count)]
  if self.starts!=sorted(set(self.starts)):raise ValueError('nonunique unwind entries')
  self.text_end=sec['.text'][3]+sec['.text'][5];self.starts=[x for x in self.starts if sec['.text'][3]<=x<self.text_end]
  self.ends=self.starts[1:]+[self.text_end]
 def at(self,va,n):
  for off,start,size in self.loads:
   if start<=va and va+n<=start+size:return self.data[off+va-start:off+va-start+n]
  raise ValueError('code outside load segment')
 def body(self,i):
  if not 0<=i<len(self.starts):raise ValueError('function absent')
  if self.ends[i]-self.starts[i]>2*1024*1024:raise ValueError('function bound exceeded')
  return self.at(self.starts[i],self.ends[i]-self.starts[i])

def compare(old,new,pins):
 wanted={};owners={}
 for p in pins:
  va=int(p['va'],0);i=bisect.bisect_right(old.starts,va)-1
  raw=old.body(i);norm=normalized(raw);key=hashlib.sha256(norm).hexdigest();wanted.setdefault(key,[]).append(p['va']);owners[p['va']]=(i,va-old.starts[i],key,len(raw))
 hits={key:[] for key in wanted}
 for i in range(len(new.starts)):
  raw=new.body(i)
  # Function size and full normalized instruction stream must both match.
  if len(raw) not in {v[3] for v in owners.values()}:continue
  digest=hashlib.sha256(normalized(raw)).hexdigest()
  if digest in hits:hits[digest].append(i)
 return [{'old_va':p['va'],'old_function':hex(old.starts[owners[p['va']][0]]),'function_bytes':owners[p['va']][3],
  'matches':[hex(new.starts[i]+owners[p['va']][1]) for i in hits[owners[p['va']][2]]],
  'method':'full_normalized_unwind_function','execution_allowed':False} for p in pins]
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('old',type=Path);p.add_argument('new',type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
 root=Path(__file__).resolve().parents[1];contract=json.loads((root/'profiles/native-code-contract.json').read_text());old=Image(a.old);new=Image(a.new)
 if hashlib.sha256(old.data).hexdigest()!=contract['library_sha256']:raise ValueError('unaudited reference')
 report={'new_library_sha256':hashlib.sha256(new.data).hexdigest(),'pins':compare(old,new,contract['pins']),'native_calls':False}
 with a.output.open('x') as f:json.dump(report,f,indent=2)
 a.output.chmod(0o600);print(json.dumps({'unique':sum(len(x['matches'])==1 for x in report['pins']),'ambiguous':sum(len(x['matches'])>1 for x in report['pins']),'missing':sum(not x['matches'] for x in report['pins'])}))
