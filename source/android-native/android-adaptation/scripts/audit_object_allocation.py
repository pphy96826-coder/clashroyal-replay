"""Read-only evidence of allocation sizes at direct constructor call sites.

Recognize a deliberately narrow sequence: MOVZ W0, size; BL allocator;
non-clobbering argument MOVs; BL constructor. Other patterns remain unknown.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from compare_client_functions import Image


def branch_target(word, pc):
    if word & 0xfc000000 != 0x94000000:
        return None
    immediate = word & 0x3ffffff
    if immediate & (1 << 25):
        immediate -= 1 << 26
    return pc + immediate * 4


def safe_argument_move(word):
    # Only register MOV and unshifted MOVZ, to registers other than X/W0.
    # A store, indirect call or unrecognized instruction ends the proof.
    register_move = word & 0x7fe0ffe0 == 0x2a0003e0
    immediate_move = word & 0xffe00000 == 0x52800000
    return word & 31 != 0 and (register_move or immediate_move)


def allocations(image, constructor, allocator):
    hits = []
    unknown = []
    for offset, start, length in image.loads:
        raw = image.data[offset:offset+length]
        for pos in range(0, len(raw)//4*4, 4):
            word = struct.unpack_from('<I', raw, pos)[0]
            if branch_target(word, start+pos) != constructor:
                continue
            call = start+pos
            recognized = False
            for distance in range(1, 13):
                before = pos-distance*4
                if before < 4:
                    break
                candidate = struct.unpack_from('<I', raw, before)[0]
                if branch_target(candidate, start+before) == allocator:
                    mov = struct.unpack_from('<I', raw, before-4)[0]
                    if mov & 0xffe0001f != 0x52800000:
                        break
                    size = (mov >> 5) & 0xffff
                    if not 1 <= size <= 1024*1024:
                        break
                    between = [struct.unpack_from('<I', raw, p)[0]
                               for p in range(before+4, pos, 4)]
                    if not all(safe_argument_move(w) for w in between):
                        break
                    hits.append(dict(constructor_call=hex(call),
                                     allocation_call=hex(start+before), bytes=size))
                    recognized = True
                    break
                # Do not reach across another call or arbitrary operations.
                if not safe_argument_move(candidate):
                    break
            if not recognized:
                unknown.append(hex(call))
    sizes = sorted({row['bytes'] for row in hits})
    return dict(constructor_candidate=hex(constructor), allocator_candidate=hex(allocator),
                matched_calls=hits, unrecognized_calls=unknown, observed_sizes=sizes,
                consistent=bool(hits) and len(sizes) == 1,
                native_execution_allowed=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('apk', type=Path)
    parser.add_argument('--constructor', type=lambda v: int(v, 0), required=True)
    parser.add_argument('--allocator', type=lambda v: int(v, 0), required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    image = Image(args.apk)
    result = allocations(image, args.constructor, args.allocator)
    result['library_sha256'] = hashlib.sha256(image.data).hexdigest()
    result['schema'] = 'royale-replay.object-allocation-audit.v1'
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2)
    args.output.chmod(0o600)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
