"""Ownership for idle retained MuMu bootstrap mappings, never foreign modules."""
import re,json,hashlib
TOKENS=('libphone_replay_','libcr_web_','libcr_private_','libcr_direct_')
ATTEMPT=re.compile(r'(?:bootstrap-v[234]|deal-check-[0-9]{1,2}|ability-candidate-[0-9]{1,3}|bootstrap-init|seed-(?:[0-9]|[1-5][0-9]|60)-(?:(?:deal|recal)-(?:[0-9]|1[01])|(?:v-|r-|r(?:[0-9]|1[0-9]|2[0-3])-)?candidate-[0-9]{1,3}))')

def released_resources(receipt):
    return (receipt.get('native_transport')=='mumu-nativebridge-v1'
        and receipt.get('component_retained_idle') is True
        and receipt.get('resource_cleanup_verified') is True
        and receipt.get('retained_code_verified') is True
        and receipt.get('requires_process_exit_for_unload') is True
        and receipt.get('publication')==1 and receipt.get('source_bootstrap_verified') is True
        and receipt.get('observer_released') is True and receipt.get('mumu_module_retained_safe') is True
        and receipt.get('module_retained_for_translated_return_safety') is True
        and receipt.get('detached') is True
        and (receipt.get('errors')==[] or (receipt.get('source_rejected_after_cleanup') is True
            and receipt.get('private_source_execution_complete') is False
            and isinstance(receipt.get('source_failure_detail'),str)
            and receipt.get('errors')==['RuntimeError: '+receipt['source_failure_detail']]
            and re.fullmatch('[a-f0-9]{64}',receipt.get('source_execution_sha256','')))))

def assert_component_ownership(maps,owned):
    found=set()
    for row in maps.splitlines():
        if any(token in row for token in TOKENS):
            fields=row.split()
            if len(fields)<6 or fields[-1] not in owned:
                raise RuntimeError('previous or foreign native component still owns game')
            found.add(fields[-1])
    if found!=set(owned):raise RuntimeError('retained component mapping changed')

def retained_paths(directory,identity,session):
    paths=set();records=list(directory.glob('*-result.json'))
    if len(records)>256:raise ValueError('too many retained native receipts')
    from mumu_runtime import component_code_ranges
    for record in records:
        receipt=json.loads(record.read_text())
        if not receipt.get('component_retained_idle'):continue
        attempt=record.name.removesuffix('-result.json')
        if not ATTEMPT.fullmatch(attempt) or not released_resources(receipt):
            raise RuntimeError('unproven retained component')
        binding=json.loads((directory/(attempt+'-binding.json')).read_text())
        component=json.loads((directory/(attempt+'-component.json')).read_text())
        if binding['identity']!=identity or binding.get('scene') is not False:
            raise RuntimeError('retained component belongs to another generation or scene')
        if receipt.get('retained_component_path')!=component['device_path'] or receipt.get('retained_component_sha256')!=component['sha256']:
            raise RuntimeError('retention receipt differs from the bound module')
        if receipt.get('source_rejected_after_cleanup'):
            source=(directory/(attempt+'-source-execution.json')).read_bytes()
            from source_completion import source_failure,source_completed
            report=json.loads(source)
            if (hashlib.sha256(source).hexdigest()!=receipt['source_execution_sha256']
                or source_failure(report)!=receipt['source_failure_detail']
                or source_completed(report,binding['source_event_count'])):
                raise RuntimeError('rejected candidate cleanup lacks its exact source report')
        if component['sha256']!=binding['binary_sha256'] or component['exports']!=binding['exports']:
            raise RuntimeError('retained component differs from immutable binding')
        component_code_ranges(type(session)(identity),component)
        if component['device_path'] in paths:raise RuntimeError('duplicate retained module')
        paths.add(component['device_path'])
    return paths
