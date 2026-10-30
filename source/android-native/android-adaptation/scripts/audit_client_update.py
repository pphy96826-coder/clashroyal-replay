"""Offline client update audit. Never attaches, executes, or approves unknown code."""
import argparse,hashlib,json,struct,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MAX=128*1024*1024

def audit(apk,contract):
 with zipfile.ZipFile(apk) as z:
  entry=z.getinfo('lib/arm64-v8a/libg.so')
  if not 64<=entry.file_size<=MAX:raise ValueError('library size outside audit limit')
  with z.open(entry) as f:data=f.read(MAX+1)
 if len(data)!=entry.file_size:raise ValueError('incomplete library')
 if data[:6]!=b'\x7fELF\x02\x01' or struct.unpack_from('<H',data,18)[0]!=183:raise ValueError('expected ARM64 ELF')
 digest=hashlib.sha256(data).hexdigest()
 phoff=struct.unpack_from('<Q',data,32)[0];phsize,phnum=struct.unpack_from('<HH',data,54)
 if phsize!=56 or phnum>256 or phoff+phsize*phnum>len(data):raise ValueError('invalid ELF program table')
 segments=[]
 for i in range(phnum):
  typ,flags,off,va,pa,size,mem,align=struct.unpack_from('<IIQQQQQQ',data,phoff+i*phsize)
  if typ==1 and flags&1 and off+size<=len(data):segments.append((off,va,size))
 pins=[]
 for pin in contract['pins']:
  va=int(pin['va'],0);n=pin['size'];block=None
  for off,start,size in segments:
   if start<=va and va+n<=start+size:block=data[off+va-start:off+va-start+n];break
  pins.append({'va':pin['va'],'matches_at_audited_location':block is not None and hashlib.sha256(block).hexdigest()==pin['file_sha256']})
 supported=digest==contract['library_sha256']
 return {'schema':'royale-replay.client-update-audit.v1','library_sha256':digest,'library_bytes':len(data),
  'supported':supported,'adaptation_required':not supported,'pins':pins,
  'matching_pins':sum(p['matches_at_audited_location'] for p in pins),'total_pins':len(pins),
  'native_calls':False,'game_apk_changed':False,'automatic_approval':False,
  'next_step':'rebuild_current_process_runtime' if supported else 'new_engine_adapter_and_roundtrip_validation_required'}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('apk',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 result=audit(a.apk,json.loads((ROOT/'profiles/native-code-contract.json').read_text()))
 with a.output.open('x') as f:json.dump(result,f,indent=2)
 a.output.chmod(0o600)
 print(json.dumps({k:v for k,v in result.items() if k!='pins'}))
if __name__=='__main__':main()
