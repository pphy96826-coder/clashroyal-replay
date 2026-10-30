"""Offline whole-function and call-graph candidate audit. Never enables execution."""
import argparse,bisect,hashlib,json,struct
from collections import defaultdict
from pathlib import Path
from compare_client_functions import Image,normalized

def descriptors(image):
 out=[];index=defaultdict(list)
 for i in range(len(image.starts)):
  body=image.body(i);stream=normalized(body);digest=hashlib.sha256(stream).hexdigest();out.append((digest,stream));index[digest].append(i)
 return out,index

def branches(image,index):
 raw=image.body(index);va=image.starts[index];result=[]
 for pos in range(0,len(raw)//4*4,4):
  word=struct.unpack_from('<I',raw,pos)[0]
  if word&0x7c000000!=0x14000000:continue
  imm=word&0x3ffffff
  if imm&(1<<25):imm-=1<<26
  target=va+pos+imm*4;j=bisect.bisect_right(image.starts,target)-1
  if j>=0 and image.starts[j]==target:result.append((pos,j))
 return result

def incoming_pin_candidate(old,new,old_index,new_index,va):
 """An incoming edge locates a function, not unchanged offsets inside it.

 A changed function may insert instructions before an internal helper. Only
 the entry itself or a unique intact normalized pin can locate that helper.
 """
 if va==old.starts[old_index]:return hex(new.starts[new_index]),'function_entry'
 reference=normalized(old.at(va,32));body=new.body(new_index);matches=[]
 for offset in range(0,len(body)-31,4):
  if normalized(body[offset:offset+32])==reference:matches.append(new.starts[new_index]+offset)
 if len(matches)==1:return hex(matches[0]),'unique_internal_pin'
 return None,'internal_pin_ambiguous' if matches else 'internal_pin_not_found'

def resolve(old,new,pins):
 a,ai=descriptors(old);b,bi=descriptors(new)
 candidates={i:list(bi.get(h,[])) for i,(h,_) in enumerate(a)}
 # Disambiguate by direct call relations wherever the target already has a unique candidate.
 checks=0;removed=0
 for iteration in range(8):
  anchors={i:v[0] for i,v in candidates.items() if len(v)==1};changed=False
  for i,choices in candidates.items():
   if not choices or len(choices)>128:continue
   edges=[(pos,target) for pos,target in branches(old,i) if target in anchors]
   if not edges:continue
   allowed=[]
   for choice in choices:
    outgoing=dict(branches(new,choice));checks+=len(edges)
    if all(outgoing.get(pos)==anchors[target] for pos,target in edges):allowed.append(choice)
   if allowed!=choices:removed+=len(choices)-len(allowed);candidates[i]=allowed;changed=True
  if not changed:break
 anchors={i:v[0] for i,v in candidates.items() if len(v)==1}
 # An unchanged caller supplies a bounded observation of its callee, even if
 # the callee body is changed or transformed in the on-disk image. Such results
 # remain separately labeled candidates, never full-body equivalence proofs.
 incoming=defaultdict(list)
 for caller,choice in anchors.items():
  outgoing=dict(branches(new,choice))
  for pos,target in branches(old,caller):
   if pos in outgoing:incoming[target].append((caller,pos,outgoing[pos]))
 inferred={}
 for target,evidence in incoming.items():
  destinations={x[2] for x in evidence};callers={x[0] for x in evidence}
  if len(destinations)!=1:continue
  destination=next(iter(destinations))
  if len(callers)>=2 or a[target][0]==b[destination][0]:
   inferred[target]={'index':destination,'independent_callers':len(callers),'call_sites':len(evidence)}
 positions=sorted(anchors)
 reports=[]
 import difflib
 for pin in pins:
  va=int(pin['va'],0);i=bisect.bisect_right(old.starts,va)-1;matches=candidates[i];reason='whole_function_and_calls';ranked=[]
  if not matches:
   pos=bisect.bisect_left(positions,i);left=positions[pos-1] if pos else None;right=positions[pos] if pos<len(positions) else None
   if left is not None and right is not None and 0<anchors[right]-anchors[left]<=80 and right-left<=80:
    for j in range(anchors[left]+1,anchors[right]):
     # Compare full fixed-width instructions, not individual byte frequencies.
     aw=list(struct.unpack('<'+'I'*(len(a[i][1])//4),a[i][1]));bw=list(struct.unpack('<'+'I'*(len(b[j][1])//4),b[j][1]))
     if max(len(aw),len(bw))>8192 or min(len(aw),len(bw))<max(len(aw),len(bw))*.65:continue
     score=difflib.SequenceMatcher(None,aw,bw,autojunk=False).ratio()
     if score>=.65:ranked.append({'va':hex(new.starts[j]),'score':round(score,6),'bytes':len(b[j][1])})
    ranked=sorted(ranked,key=lambda x:x['score'],reverse=True)[:5]
   reason='changed_function_candidates'
  call=inferred.get(i);incoming_match,incoming_method=incoming_pin_candidate(old,new,i,call['index'],va) if call else (None,None)
  reports.append({'incoming_call_candidate':incoming_match,'incoming_pin_method':incoming_method,'incoming_evidence':call,'old_va':pin['va'],'old_function':hex(old.starts[i]),'old_function_bytes':len(a[i][1]),'method':reason,
   'matches':[hex(new.starts[j]+va-old.starts[i]) for j in matches], 'similar_functions':ranked,'execution_allowed':False})
 return {'unique_function_anchors':len(anchors),'graph_checks':checks,'candidates_rejected':removed,'incoming_mappings':len(inferred),'pins':reports,'native_calls':False}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('old',type=Path);p.add_argument('new',type=Path);p.add_argument('--output',type=Path,required=True);args=p.parse_args();root=Path(__file__).resolve().parents[1];contract=json.loads((root/'profiles/native-code-contract.json').read_text())
 old=Image(args.old);new=Image(args.new)
 if hashlib.sha256(old.data).hexdigest()!=contract['library_sha256']:raise ValueError('reference mismatch')
 report=resolve(old,new,contract['pins']);report['library_sha256']=hashlib.sha256(new.data).hexdigest()
 with args.output.open('x') as f:json.dump(report,f,indent=2)
 args.output.chmod(0o600);print(json.dumps({k:v for k,v in report.items() if k!='pins'}));print(json.dumps([{'old':x['old_va'],'matches':len(x['matches']),'similar':x['similar_functions'][:2]} for x in report['pins']]))
