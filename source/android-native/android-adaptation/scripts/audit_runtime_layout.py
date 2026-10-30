"""Compare authenticated loaded code, including object-member displacement changes.

This audit produces evidence, never an executable adapter. PC-relative address
relocation is normalized separately from member offsets; the latter must remain
visible. Runtime code can differ from the bytes stored in the APK.
"""
import argparse
from collections import defaultdict
import difflib
import hashlib
import json
import os
from pathlib import Path
import struct

from compare_client_functions import normalized


def digest(data):
    return hashlib.sha256(data).hexdigest()


def member_operand(word):
    """Decode only ordinary scalar immediate memory accesses and ADD pointers.

    Do not guess SIMD, register offsets, literal loads or writeback semantics.
    The returned shape retains operation, width, base and destination registers.
    """
    base = (word >> 5) & 31
    if word & 0x3b000000 == 0x39000000 and not word & (1 << 26):
        scale = (word >> 30) & 3
        mask = 0xfff << 10
        return dict(kind='scalar_memory', base=base, register=word & 31,
                    offset=((word >> 10) & 0xfff) << scale,
                    shape=word & ~mask)
    if word & 0xffc00000 == 0x91000000:  # ADD Xd, Xn, #imm12, no shift
        mask = 0xfff << 10
        return dict(kind='member_address', base=base, register=word & 31,
                    offset=(word >> 10) & 0xfff, shape=word & ~mask)
    return None


def compare_loaded(old, new, *, self_register=19):
    if (not old or not new or len(old) % 4 or len(new) % 4
            or max(len(old), len(new)) > 65536 or not 19 <= self_register <= 28):
        raise ValueError('bounded ARM64 functions and a callee-saved self register required')
    # A register number is not an object identity. Both bodies must explicitly
    # bind this callee-saved register to the incoming object pointer X0.
    bind_self = 0xaa0003e0 | self_register  # MOV Xself, X0
    old_words = struct.unpack('<' + 'I' * (len(old) // 4), old)
    new_words = struct.unpack('<' + 'I' * (len(new) // 4), new)
    self_bound = bind_self in old_words[:24] and bind_self in new_words[:24]
    def object_positions(instructions):
        valid = set()
        bound = False
        called = False
        for pos, word in enumerate(instructions):
            if bound:
                valid.add(pos)
            if word == bind_self and not called:
                bound = True
                continue
            if word & 0xfc000000 == 0x94000000:
                called = True
            # Keep callee-saved Xself across calls, but not across reuse as a
            # scalar temporary (including writes to its W register alias).
            branch = word & 0x7c000000 == 0x14000000 or word & 0x7e000000 in (0x34000000, 0x36000000)
            branch = branch or word & 0xff000010 == 0x54000000
            store = word & 0x3b000000 == 0x39000000 and not word & (1 << 22)
            pair_store = word & 0x3a400000 == 0x28000000
            if word & 31 == self_register and not (branch or store or pair_store):
                bound = False
        return valid
    old_objects, new_objects = object_positions(old_words), object_positions(new_words)
    a = struct.unpack('<' + 'I' * len(old_words), normalized(old))
    b = struct.unpack('<' + 'I' * len(new_words), normalized(new))
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    differences = []
    changes = []
    unexplained = 0
    for tag, i, j, k, l in matcher.get_opcodes():
        if tag == 'equal':
            continue
        row = dict(kind=tag, old_offset=i * 4, new_offset=k * 4,
                   old_bytes=(j-i)*4, new_bytes=(l-k)*4)
        recognized = 0
        if self_bound and tag == 'replace' and j-i == l-k:
            for left, right in zip(range(i, j), range(k, l)):
                before = member_operand(old_words[left])
                after = member_operand(new_words[right])
                if (left in old_objects and right in new_objects
                        and before and after and before['base'] == self_register
                        and after['base'] == self_register
                        and before['shape'] == after['shape']
                        and before['offset'] != after['offset']):
                    changes.append(dict(kind=before['kind'],
                                        old_instruction_offset=left*4,
                                        new_instruction_offset=right*4,
                                        old_member_offset=hex(before['offset']),
                                        new_member_offset=hex(after['offset'])))
                    recognized += 1
        row['recognized_member_changes'] = recognized
        unexplained += max(j-i, l-k)-recognized
        differences.append(row)
    return dict(old_bytes=len(old), new_bytes=len(new),
                normalized_equal=a == b, normalized_similarity=matcher.ratio(),
                self_register_bound=self_bound, member_changes=changes,
                unexplained_instruction_changes=unexplained, differences=differences,
                native_execution_allowed=False)


def summarize(functions):
    evidence = defaultdict(list)
    for item in functions:
        for change in item['comparison']['member_changes']:
            evidence[change['old_member_offset'], change['new_member_offset']].append(
                dict(function=item['name'], **change))
    by_old = defaultdict(set)
    for before, after in evidence:
        by_old[before].add(after)
    # Multiple references in one function are not independent confirmation.
    return [dict(old_member_offset=before, new_member_offset=after,
                 references=len(rows), functions=sorted({r['function'] for r in rows}),
                 corroborated=len({r['function'] for r in rows}) >= 2,
                 conflicting=len(by_old[before]) != 1, evidence=rows)
            for (before, after), rows in sorted(evidence.items())]


def audit(reference, observed):
    """Files are local private audit inputs, not executable update downloads."""
    old = json.loads(reference.read_text())
    new = json.loads(observed.read_text())
    if (old.get('schema') != 'royale-replay.loaded-reference.v1'
            or new.get('schema') != 'royale-replay.loaded-code-snapshot.v1'
            or new.get('native_calls') is not False
            or new.get('game_memory_written') is not False
            or new.get('generation_verified') is not True):
        raise ValueError('authenticated read-only capture manifests required')
    functions = []
    for name, spec in old['functions'].items():
        if name not in new['functions']:
            raise ValueError('missing loaded function: ' + name)
        capture = new['functions'][name]
        before = verified_file(reference.parent, spec)
        after = verified_file(observed.parent, capture)
        functions.append(dict(name=name, old_va=spec['va'], new_candidate_va=capture['va'],
                              old_sha256=digest(before), new_sha256=digest(after),
                              comparison=compare_loaded(before, after,
                                                        self_register=spec.get('self_register', 19))))
    return dict(schema='royale-replay.loaded-layout-audit.v1',
                old_library_sha256=old['library_sha256'],
                new_library_sha256=new['library_sha256'], functions=functions,
                field_changes=summarize(functions),
                object_layout_verified=False, native_execution_allowed=False,
                native_calls=False, game_memory_written=False)


def verified_file(directory, spec):
    # Keep captures together and reject traversal or redirected private inputs.
    name = spec['file']
    if Path(name).name != name or name in ('', '.', '..'):
        raise ValueError('capture must be a sibling file')
    target = directory / name
    if target.is_symlink() or not 0 < spec['bytes'] <= 65536:
        raise ValueError('invalid capture file')
    if target.stat().st_size != spec['bytes']:
        raise ValueError('capture size differs')
    data = target.read_bytes()
    if digest(data) != spec['sha256']:
        raise ValueError('capture hash differs')
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference', type=Path)
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.reference, args.snapshot)
    # Create private from the first write, without a world-readable interval.
    with open(args.output, 'x', opener=lambda p, f: os.open(p, f, 0o600)) as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(dict(functions=len(report['functions']),
                          field_changes=[{k: v for k, v in row.items() if k != 'evidence'}
                                         for row in report['field_changes']],
                          native_execution_allowed=False)))


if __name__ == '__main__':
    main()
