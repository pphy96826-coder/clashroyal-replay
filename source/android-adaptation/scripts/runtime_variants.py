"""Generate isolated adapters from checked-in audited contracts and owned source."""
import json
import re


def expand(contents, root):
    # Rebuilding twice must not retain stale files from a former variant.
    result={name:raw for name,raw in contents.items() if not name.startswith('variants/')}
    for path in sorted((root/'profiles').glob('native-runtime-contract-*.approved.json')):
        contract=json.loads(path.read_text());digest=contract['library_sha256']
        if (not re.fullmatch('[0-9a-f]{64}',digest) or contract.get('supported') is not True
                or contract.get('native_execution_allowed') is not True
                or contract.get('contains_process_handles') is not False):
            raise ValueError('Incomplete audited client variant')
        version=contract['version']
        aliases=json.loads((root/'profiles'/('client-aliases-'+version+'.json')).read_text())
        aliases={int(a,0):int(b,0) for a,b in aliases.items()}
        def relocate(text):
            return re.sub(r'0x[0-9a-fA-F]+',lambda m:hex(aliases[int(m[0],0)]) if int(m[0],0) in aliases else m[0],text)
        prefix='variants/'+digest+'/'
        for name,raw in contents.items():
            if not name.startswith('app/') or name.startswith('app/mumu-support/'):continue
            if name.endswith(('.py','.cpp','.h')):
                raw=relocate(raw.decode()).encode()
            if name.endswith('.py'):
                # Evidence validators are pinned too: the new adapter must
                # require the new full hash, never the base adapter's hash.
                raw=raw.replace(b'c6b2482a2f1fbd2e15c99df7fb18ba3d5596b77b3a81930d3638241a3c37fe55',digest.encode())
            if name=='app/native-src/official-web-replay/client_layout.h':
                text=raw.decode()
                for key in ('avatar','domain','deal','unit','controller','vtables'):
                    old='active_'+key+'='+key+'_3842'
                    if text.count(old)!=1:raise ValueError('Client layout selector changed')
                    text=text.replace(old,'active_'+key+'='+key+'_3852')
                raw=text.encode()
            if name=='app/mumu_platform.py':
                raw=raw.replace(b"def support():return Path(__file__).resolve().parent/'mumu-support'",b"def support():return Path(__file__).resolve().parents[3]/'app/mumu-support'")
            if name=='app/device_build.py':
                raw=raw.replace(b"(('frame',0xb10),('interpolate',0xb08))",b"(('frame',0xb30),('interpolate',0xb28))")
            if name.endswith('/runtime_probe.cpp'):
                text=raw.decode()
                for pin in contract['worker_validation_pins']+contract['entry_validation_pins']:
                    pattern=r'\{'+re.escape(pin['va'])+r',\s*0x[0-9a-fA-F]+\}'
                    text,n=re.subn(pattern,'{'+pin['va']+', '+pin['word']+'}',text)
                    if n!=1:raise ValueError('Runtime validation pin not unique')
                raw=text.encode()
            result[prefix+name]=raw
        result[prefix+'app/native-contract.json']=path.read_bytes()
        result[prefix+'app/native-code-contract.json']=(root/'profiles'/('native-code-contract-'+version+'.approved.json')).read_bytes()
    return result
