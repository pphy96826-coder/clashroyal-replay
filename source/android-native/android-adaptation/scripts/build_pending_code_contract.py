"""Build non-executable update evidence from a fresh complete pin snapshot.

Never installs a contract or changes the approved native-code-contract.json.
Even a complete pin set does not prove object layout or replay correctness.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

from audit_runtime_layout import verified_file
from compare_client_functions import Image


def build(reference,candidates,snapshot,directory,image):
    library_hash=hashlib.sha256(image.data).hexdigest()
    if (candidates.get('schema')!='royale-replay.code-candidates.v1'
            or snapshot.get('schema')!='royale-replay.loaded-code-snapshot.v1'
            or snapshot.get('generation_verified') is not True
            or snapshot.get('native_calls') is not False
            or snapshot.get('game_memory_written') is not False
            or candidates.get('library_sha256')!=library_hash
            or snapshot.get('library_sha256')!=library_hash):
        raise ValueError('matching read-only snapshot identity required')
    expected={'pin-'+format(int(row['va'],0),'x'):row for row in reference['pins']}
    if (len(expected)!=len(reference['pins']) or not expected
            or set(candidates['functions'])!=set(expected)
            or set(snapshot['functions'])!=set(expected)):
        raise ValueError('complete unique reference pin set required')
    pins=[];destinations=set()
    for name,old in expected.items():
        candidate=candidates['functions'][name];observed=snapshot['functions'][name]
        va=int(candidate['va'],0)
        if (old['size']!=32 or candidate['bytes']!=32 or observed['bytes']!=32
                or va<=0 or va%4 or va in destinations or int(observed['va'],0)!=va):
            raise ValueError('unique aligned 32-byte pin correspondence required')
        destinations.add(va)
        raw=verified_file(directory,observed)
        file_bytes=image.at(va,32)
        if len(file_bytes)!=32:
            raise ValueError('pin leaves executable file range')
        pins.append(dict(reference_va=old['va'],va=hex(va),size=32,
                         file_sha256=hashlib.sha256(file_bytes).hexdigest(),
                         runtime_sha256=hashlib.sha256(raw).hexdigest()))
    return dict(schema='royale-replay.pending-native-code-contract.v1',
                library_sha256=library_hash,reference_library_sha256=reference['library_sha256'],
                contains_process_handles=False,supported=False,native_execution_allowed=False,
                original_entry_count=len(expected),all_entries_located=True,
                loaded_code_captured=True,object_layout_and_roundtrip_verified=False,pins=pins)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--candidates',type=Path,required=True)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--apk',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not args.output.name.endswith('.pending.json'):
        raise ValueError('output must be an explicit .pending.json file')
    result=build(json.loads(args.reference.read_text()),json.loads(args.candidates.read_text()),
                 json.loads(args.snapshot.read_text()),args.snapshot.parent,Image(args.apk))
    with open(args.output,'x',opener=lambda p,f:os.open(p,f,0o600)) as stream:
        json.dump(result,stream,indent=2)
    print(json.dumps(dict(pins=len(result['pins']),supported=False,native_execution_allowed=False,
                          loaded_transforms=sum(p['file_sha256']!=p['runtime_sha256'] for p in result['pins']))))


if __name__=='__main__':main()
