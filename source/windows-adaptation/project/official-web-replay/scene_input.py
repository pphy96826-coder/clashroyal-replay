"""Pure, lossless local replay scene input; validate before touching a device."""
import json
from bootstrap_input import render
from tower_profiles import render_towers


def render_scene(preparation,replay,playback_speed=1):
    if type(playback_speed) not in (int,float) or playback_speed not in (.25,.5,1,2,4):
        raise ValueError('unsupported replay playback speed')
    render(preparation,True,replay)  # Same strict source/identity/card/tick guards.
    payload=json.dumps(replay,ensure_ascii=True,separators=(',',':'))
    text='static const char scene_json[]='+json.dumps(payload)+';\n'
    preview=preparation.get('diagnostic_preview')
    stop=0
    if preview:
        stop=preview.get('stop_tick')
        if (preview.get('diagnostic_only') is not True or preview.get('complete_replay_verified') is not False
                or preview.get('preview_event_count')!=len(preparation['events'])
                or len(preview.get('original_source_events',[]))!=preview.get('original_source_event_count')
                or preview['original_source_events'][:len(preparation['events'])]!=preparation['events']
                or type(stop) is not int or not preparation['events'][-1]['source_tick_20hz']<stop<preparation['initialization_only']['endTick']):
            raise ValueError('invalid explicitly incomplete diagnostic preview')
    text+='#define WEB_DIAGNOSTIC_STOP_TICK '+str(stop)+'\n'
    text+=render_towers(preparation,'scene')
    text+='static constexpr float scene_initial_speed='+str(float(playback_speed))+'f;\n'
    owners={p['native_owner']:p['synthetic_native_identity'] for p in preparation['participants'].values()}
    text+='static const unsigned scene_identities[2][2]={'+','.join('{'+str(owners[i]['hi'])+','+str(owners[i]['lo'])+'}' for i in (0,1))+'};\n'
    text+='struct SceneEvent{int tick,kind;};\nstatic const SceneEvent scene_events[]={'+','.join('{'+str(e['source_tick_20hz'])+','+str(e['native_request']['command_type'])+'}' for e in preparation['events'])+'};\n'
    return text
