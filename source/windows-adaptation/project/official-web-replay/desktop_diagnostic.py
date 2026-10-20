"""User-selected diagnostic queue playback, isolated from full replay/cache gates."""
import hashlib
from pathlib import Path
from diagnostic_prefix import preview_inputs


def play(player, html, evidence, speed=1):
    from console_backend import PROJECT, read_json, write_new
    from align_native_deal import calibrate, deck_fingerprint
    from timing_policy import GLOBAL_DELAY_TICKS
    player.checkpoint();player.new_folder()
    raw=Path(html).read_bytes()
    if not 0<len(raw)<=25*1024*1024 or hashlib.sha256(raw).hexdigest()!=evidence.get('source_sha256'):
        raise ValueError('诊断HTML身份不符')
    if evidence.get('user_authorized') is not True:raise ValueError('缺少明确诊断预览授权')
    original=evidence['preparation']
    subset,native=preview_inputs(original,evidence['report'],evidence['receipt'],authorized=True)
    source_html=player.folder/'source.html';source_html.write_bytes(raw)
    source=player.folder/'source.json'
    player.command('import_replay.py',source_html,'--project-root',PROJECT,'--output',source)
    doc=read_json(source)
    if doc['source_sha256']!=original['source_sha256']:raise ValueError('诊断原始源已改变')
    if player.discover_owned():raise RuntimeError('已有本地回放现场，请先安全停止；诊断预览不会覆盖战斗')
    observation=player.observation()
    levels=player.folder/'levels.json';towers=player.folder/'towers.json';initial=player.folder/'initial.json'
    player.command('observe_card_levels.py','--observation',observation,'--source',source,'--output',levels)
    player.command('observe_tower_catalog.py','--observation',observation,'--output',towers)
    player.command('prepare_native_replay.py',source,'--level-evidence',levels,'--tower-evidence',towers,'--output',initial)
    shifted=player.folder/'shifted.json'
    player.command('timing_policy.py','--preparation',initial,'--offset-ticks',GLOBAL_DELAY_TICKS,'--output',shifted)
    seen=[];prep=shifted
    for number in range(12):
        current=read_json(prep);seen.append(deck_fingerprint(current))
        _,receipt=player.probe(prep,observation)
        aligned=calibrate(current,read_json(receipt),seen)
        prep=player.folder/('calibrated-'+str(number)+'.json');write_new(prep,aligned)
        if aligned['native_deal_ready']:break
    else:raise RuntimeError('诊断初始牌序校准失败，未发布画面')
    for key in ('events','initialization_only','native_initial_tower_hp'):
        if aligned.get(key)!=original.get(key):raise ValueError('新初始化与诊断分支不符：'+key)
    prep=player.folder/'diagnostic-preparation.json';full=player.folder/'complete-native.json'
    write_new(prep,subset);write_new(full,native)
    player.emit('match',dict(doc,diagnostic_preview=subset['diagnostic_preview']))
    player.stage('诊断预览：仅播放已成功执行的前缀，在分歧点暂停；不是完整回放，也不写成功缓存。')
    observation=player.observation()
    attempt,receipt=player.probe(prep,observation,execute=True,native=full,scene=True,speed=speed)
    player.emit('playing',dict(attempt=attempt,event_count=len(subset['events']),duration=subset['diagnostic_preview']['stop_tick']/20,
        speed=speed,receipt=str(receipt),diagnostic_only=True,complete_replay_verified=False))
