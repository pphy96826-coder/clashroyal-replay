"""Validate terminal retained modules without guessing translated stack liveness."""
import hashlib
import json

def released(receipt):
    return receipt.get('component_unloaded') or (
        receipt.get('mumu_module_retained_safe') is True and receipt.get('observer_released') is True
        and receipt.get('module_retained_for_translated_return_safety') is True)

def verify_retained(root,maps,identity):
    mapped={line.split()[-1] for line in maps.splitlines() if len(line.split())>=6 and
        any(token in line.split()[-1] for token in ('libcr_private_','libcr_direct_','libcr_web_'))}
    if len(mapped)>32:raise RuntimeError('retained native module limit reached; restart the client before another session')
    for component in root.glob('*-component.json'):
        comp=json.loads(component.read_text(encoding='utf-8'));path=comp.get('device_path')
        if path not in mapped:continue
        attempt=component.name.removesuffix('-component.json')
        binding=json.loads((root/(attempt+'-binding.json')).read_text(encoding='utf-8'))
        receipt_path=root/(attempt+'-result.json')
        if not receipt_path.exists():continue
        receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
        if binding['identity']!=identity:continue
        quarantine=root/(attempt+'-unpublished-owner.json')
        if quarantine.exists() and receipt.get('publication') is None and receipt.get('detached'):
            evidence=json.loads(quarantine.read_text(encoding='utf-8'))
            if evidence.get('identity')==identity and evidence.get('component_sha256')==comp['sha256'] and evidence.get('probe_pointer')==0:
                from client_session import ReadOnlySession
                from mapped_elf import load_bias
                from elf_contract import Elf
                from pathlib import Path
                raw=Path(comp['local_path']).read_bytes()
                if hashlib.sha256(raw).hexdigest()!=comp['sha256']:continue
                session=ReadOnlySession(identity)
                image=Elf(raw);symbol,size=image.object_symbol('_ZN12_GLOBAL__N_15probeE')
                if size!=8 or symbol!=int(evidence['probe_symbol_va'],0):continue
                if binding.get('mumu_build',{}).get('libc_binding')!='verified-game-import-absolute-symbols':continue
                base=load_bias(session.verify().splitlines(),path,image)
                address=base+symbol
                if session.read(address,8)==b'\0'*8 and session.read(address,8)==b'\0'*8:
                    session.verify();mapped.remove(path);continue
        if receipt.get('errors') or not receipt.get('detached') or not released(receipt):continue
        if receipt.get('retained_component_path')!=path or receipt.get('retained_component_sha256')!=comp['sha256']:continue
        if hashlib.sha256(__import__('pathlib').Path(comp['local_path']).read_bytes()).hexdigest()!=comp['sha256']:continue
        mapped.remove(path)
    if mapped:raise RuntimeError('unresolved previous native owner remains mapped; observe it rather than submit another task')
