"""Advisory deck/seed hints only; every run still checks the native deal and battle.

Never stores process pointers, executable components, native JSON or a result
that could bypass fresh source execution/JSON/terminal checks.
"""
import copy,hashlib,json,os,stat,uuid
from pathlib import Path

SCHEMA='royale-replay.preparation-hint.v1'
EPHEMERAL={'native_tower_evidence_sha256','native_level_evidence_sha256','source_manifest_sha256'}
ALGORITHMS=('align_native_deal.py','prepare_native_replay.py','device_import.py','device_playback.py','mumu_compile.py','native-code-contract.json')


def key_for(initial):
    semantic={k:v for k,v in initial.items() if k not in EPHEMERAL}
    hashes={name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest() for name in ALGORITHMS}
    raw=json.dumps({'schema':SCHEMA,'preparation':semantic,'algorithms':hashes},sort_keys=True,separators=(',',':')).encode()
    return hashlib.sha256(raw).hexdigest()


def _directory(files,create=False):
    directory=files/'preparation-hints';owner=files.stat()
    if create and not directory.exists():
        directory.mkdir(mode=0o700);os.chown(directory,owner.st_uid,owner.st_gid)
    info=directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=owner.st_uid or stat.S_IMODE(info.st_mode)!=0o700:raise ValueError('hint directory differs')
    return directory


def apply(initial,hint,key):
    if hint.get('schema')!=SCHEMA or hint.get('key')!=key or hint.get('source_sha256')!=initial['source_sha256']:raise ValueError('hint identity differs')
    seed=hint.get('seed')
    if type(seed) is not int or not -2**31<=seed<2**31:raise ValueError('hint seed outside bounds')
    orders=hint.get('orders')
    if not isinstance(orders,list) or len(orders)!=2:raise ValueError('hint deck count differs')
    result=copy.deepcopy(initial)
    for owner,order in enumerate(orders):
        entries=result['initialization_only']['battle']['deck'+str(owner)]['sp'];by_id={c['d']:c for c in entries}
        if len(entries)!=8 or len(by_id)!=8 or not isinstance(order,list) or len(order)!=8 or any(type(v) is not int for v in order) or len(set(order))!=8 or set(order)!=set(by_id):raise ValueError('hint changes source cards')
        result['initialization_only']['battle']['deck'+str(owner)]['sp']=[by_id[v] for v in order]
        for side,part in result['participants'].items():
            if part['native_owner']!=owner:continue
            part['deck_order']=list(order);part['cycle']['native_deal_verified']=False
            for event in result['events']:
                if event['source_side']==side and event['kind']=='play_card':event['native_request']['deck_index']=order.index(event['base_data_id'])
    result['initialization_only']['rndSeed']=seed
    result['native_deal_ready']=False
    return result


def load(files,initial):
    key=key_for(initial);detail={'key':key,'used':False,'native_verification_required':True}
    try:
        path=_directory(files)/(key+'.json');info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=files.stat().st_uid or stat.S_IMODE(info.st_mode)!=0o600 or not 0<info.st_size<=4096:raise ValueError('hint ownership or size differs')
        raw=path.read_bytes();hint=json.loads(raw)
        result=apply(initial,hint,key)
        detail.update(used=True,sha256=hashlib.sha256(raw).hexdigest())
        return result,detail
    except (OSError,ValueError,KeyError,TypeError):return copy.deepcopy(initial),detail


def save(files,initial,aligned,*,exact,roundtrip_verified):
    if not exact or not roundtrip_verified or not aligned.get('native_deal_ready'):return False
    key=key_for(initial)
    hint={'schema':SCHEMA,'key':key,'source_sha256':initial['source_sha256'],
          'seed':aligned['initialization_only']['rndSeed'],
          'orders':[[c['d'] for c in aligned['initialization_only']['battle']['deck'+str(owner)]['sp']] for owner in (0,1)]}
    apply(initial,hint,key)
    directory=_directory(files,create=True)
    if len(list(directory.glob('*.json')))>=128 and not (directory/(key+'.json')).exists():return False
    temporary=directory/(uuid.uuid4().hex+'.tmp')
    with temporary.open('x',encoding='utf-8') as stream:json.dump(hint,stream,separators=(',',':'));stream.flush();os.fsync(stream.fileno())
    owner=files.stat();os.chown(temporary,owner.st_uid,owner.st_gid);os.chmod(temporary,0o600)
    temporary.replace(directory/(key+'.json'))
    return True
