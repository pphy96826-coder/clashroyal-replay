"""Locate virtual-method slots by callee identity, not by the old slot number.

Table bases must be independently located (for example, in a constructor).
Subtracting an old slot from a relocated method can invent a false table base
when an update inserts virtual methods. This audit never enables execution.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct

from compare_client_functions import Image, sections


def relative_pointers(image):
    section = sections(image.data)['.rela.dyn']
    if section[9] != 24 or section[5] % 24 or section[4]+section[5] > len(image.data):
        raise ValueError('invalid ARM64 relocation section')
    result = {}
    for pos in range(section[4], section[4]+section[5], 24):
        address, info, addend = struct.unpack_from('<QQq', image.data, pos)
        if info & 0xffffffff == 1027:  # R_AARCH64_RELATIVE
            if address in result or address % 8 or addend < 0:
                raise ValueError('invalid or duplicate relative relocation')
            result[address] = addend
    return result


def slots(pointers, table, span, methods):
    if table <= 0 or table % 8 or not 8 <= span <= 16384 or span % 8:
        raise ValueError('bounded aligned table required')
    rows = []
    for name, address in methods.items():
        address = int(address, 0)
        matches = [hex(slot) for slot in range(0, span, 8)
                   if pointers.get(table+slot) == address]
        rows.append(dict(method=name, candidate_va=hex(address), slots=matches,
                         unique=len(matches) == 1))
    return rows


def compare_tables(old, new, before, after, old_methods, new_methods, span):
    if set(old_methods) != set(new_methods) or len(old_methods) < 2:
        raise ValueError('at least two corresponding methods required')
    tables = []
    for image, table in [(old, before), (new, after)]:
        section = sections(image.data)['.data.rel.ro']
        if not section[3] <= table < table+span <= section[3]+section[5]:
            raise ValueError('table leaves read-only relocation section')
        tables.append(relative_pointers(image))
    a = slots(tables[0], before, span, old_methods)
    b = slots(tables[1], after, span, new_methods)
    rows = [dict(method=x['method'], old_slots=x['slots'], new_slots=y['slots'],
                 unique=x['unique'] and y['unique'],
                 slot_changed=x['slots'] != y['slots']) for x, y in zip(a, b)]
    return dict(schema='royale-replay.vtable-layout-audit.v1',
                old_library_sha256=hashlib.sha256(old.data).hexdigest(),
                new_library_sha256=hashlib.sha256(new.data).hexdigest(),
                old_table=hex(before), new_candidate_table=hex(after), methods=rows,
                method_identity_validation_required=True, native_execution_allowed=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('old', type=Path)
    parser.add_argument('new', type=Path)
    parser.add_argument('--mapping', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    mapping = json.loads(args.mapping.read_text())
    result = compare_tables(Image(args.old), Image(args.new), int(mapping['old_table'], 0),
                            int(mapping['new_table'], 0), mapping['old_methods'],
                            mapping['new_methods'], mapping['span'])
    with open(args.output, 'x', opener=lambda p, f: os.open(p, f, 0o600)) as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
