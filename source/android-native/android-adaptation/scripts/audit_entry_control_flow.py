"""Check branch destinations erased by relocation normalization.

Whole normalized instruction equality does not prove identical control flow:
an internal branch can change its destination without changing its opcode.
These checks produce evidence only, never an executable runtime approval.
"""
import struct


def signed(value,bits):
    return value-(1<<bits) if value&(1<<(bits-1)) else value


def branch(word,pc):
    if word&0x7c000000==0x14000000:
        return ('call' if word&(1<<31) else 'jump',pc+4*signed(word&0x3ffffff,26),word&0xfc000000)
    if word&0xff000010==0x54000000:
        return ('conditional',pc+4*signed((word>>5)&0x7ffff,19),word&0xff00001f)
    if word&0x7e000000==0x34000000:
        return ('compare',pc+4*signed((word>>5)&0x7ffff,19),word&0xff00001f)
    if word&0x7e000000==0x36000000:
        return ('test',pc+4*signed((word>>5)&0x3fff,14),word&0xfff8001f)
    return None


def compare_flow(old,new,old_va,new_va,aliases):
    if not old or not new or len(old)%4 or len(new)%4:
        raise ValueError('aligned ARM64 functions required')
    if len(old)!=len(new):
        return dict(state='changed_instruction_positions',checked=False,native_execution_allowed=False)
    internal=0;known=0;unresolved=[];mismatches=[]
    for offset in range(0,len(old),4):
        a=branch(struct.unpack_from('<I',old,offset)[0],old_va+offset)
        b=branch(struct.unpack_from('<I',new,offset)[0],new_va+offset)
        if not a and not b:continue
        if not a or not b or a[0]!=b[0] or a[2]!=b[2]:
            mismatches.append(dict(offset=offset,reason='branch_type_changed'));continue
        if old_va<=a[1]<old_va+len(old):
            internal+=1
            if b[1]-new_va!=a[1]-old_va:
                mismatches.append(dict(offset=offset,reason='internal_destination_changed'))
        elif a[1] in aliases:
            known+=1
            if b[1]!=aliases[a[1]]:
                mismatches.append(dict(offset=offset,reason='known_callee_changed',
                                       expected=hex(aliases[a[1]]),observed=hex(b[1])))
        else:
            unresolved.append(dict(offset=offset,old_target=hex(a[1]),new_target=hex(b[1])))
    return dict(state='mismatch' if mismatches else 'checked_relations_consistent',
                checked=True,internal_branches=internal,known_calls=known,
                unresolved_external_calls=unresolved,mismatches=mismatches,
                native_execution_allowed=False)
