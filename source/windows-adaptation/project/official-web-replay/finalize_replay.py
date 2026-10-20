"""Accept ONLY a complete, genuinely dispatched native source command stream."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
from bootstrap_input import validate


def finalize(preparation,report,receipt):
    if preparation.get('diagnostic_preview'):
        raise ValueError('diagnostic preview is never a complete source replay or cache entry')
    validate(preparation)
    events=preparation['events'];commands=report['commands'];dispatch=report['dispatch']
    if receipt.get('errors') or not receipt.get('private_source_execution_complete'):
        raise ValueError('native source execution did not complete')
    if report['error'] or not report['finished'] or report['native_accepted']!=len(events):
        raise ValueError('native engine did not accept every source event and reach termination')
    if len(commands)!=len(events) or len(dispatch)!=len(events):raise ValueError('incomplete native command stream')
    for index,(event,command,execution) in enumerate(zip(events,commands,dispatch)):
        owner=preparation['participants'][event['source_side']]
        identity=owner['synthetic_native_identity'];body=command['c'];tick=event['source_tick_20hz']
        if execution!={'index':index,'kind':command['ct'],'tick':tick,'flags':3,'code':0}:
            raise ValueError('command was not executed at its source tick')
        if body['t']!=tick or body['t2']!=tick or (body['idHi'],body['idLo'])!=(identity['hi'],identity['lo']):
            raise ValueError('native command timing/identity differs from source')
        if event['kind']=='play_card':
            if command['ct']!=153 or body['sel']['os']!=event['base_data_id'] or not isinstance(body['sel']['pd'],int):
                raise ValueError('native selection differs from source card')
            if {'x':body['px'],'y':body['py']}!=event['source_position']:raise ValueError('native position differs from source')
        elif command['ct']!=189 or type(body.get('cgid')) is not int or body['cgid']<0:
            raise ValueError('native ability actor was not resolved')
    replay=copy.deepcopy(preparation['initialization_only']);replay['cmd']=copy.deepcopy(commands)
    return {'schema':'official-web-replay.complete-native.v1','native_replay':replay,
            'source_sha256':preparation['source_sha256'],'replay_tag':preparation['replay_tag'],
            'participants':copy.deepcopy(preparation['participants']),'source_events':copy.deepcopy(events),
            'native_accepted_events':len(events),'native_terminal_tick':report['tick'],
            'scene_playback_verified':False,'orientation_visually_verified':False}


def main():
    p=argparse.ArgumentParser();p.add_argument('--preparation',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True);p.add_argument('--receipt',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=finalize(json.loads(a.preparation.read_text(encoding="utf-8")),json.loads(a.report.read_text(encoding="utf-8")),json.loads(a.receipt.read_text(encoding="utf-8")))
    result['evidence_sha256']={name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in
                               [('preparation',a.preparation),('report',a.report),('receipt',a.receipt)]}
    with a.output.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({'native_commands':len(result['native_replay']['cmd']),'native_terminal_tick':result['native_terminal_tick'],
                      'scene_playback_verified':False}))


if __name__=='__main__':main()
