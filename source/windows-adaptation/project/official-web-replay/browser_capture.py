"""Validate/save the HTML already displayed in our own embedded browser.

No HTTP requests, cookie access, external browser control, or script execution.
Untrusted HTML is only parsed; exact original text is retained for the player.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from import_replay import convert, card_ids_from_html,normalize_saved_links


def replay_url(value):
    if not isinstance(value, str) or len(value) > 4096: raise ValueError('回放网址无效')
    u = urlsplit(value)
    if u.scheme != 'https' or u.hostname not in ('royaleapi.com', 'www.royaleapi.com') or u.username or u.password or u.port not in (None, 443):
        raise ValueError('只接受 RoyaleAPI 的 HTTPS 回放详情页')
    if u.path.rstrip('/') != '/replay': raise ValueError('请先打开某一场回放详情页，而不是玩家对战列表')
    query = parse_qs(u.query)
    tags = query.get('tag', [])
    if len(tags) != 1 or not re.fullmatch('[A-Z0-9]{6,32}', tags[0]): raise ValueError('网址缺少唯一回放编号')
    # Keep public replay provenance only, not arbitrary auth/tracking parameters.
    public = {k: query[k][0] for k in ('tag', 'team_tags', 'opponent_tags', 'team_crowns', 'opponent_crowns') if k in query}
    return tags[0], urlunsplit(('https', 'royaleapi.com', '/replay', urlencode(public), ''))


def save_capture(html, url, *, project, directory):
    tag, public_url = replay_url(url)
    if not isinstance(html, str) or not 0 < len(html.encode('utf-8')) <= 25 * 1024 * 1024:
        raise ValueError('页面 HTML 为空或超过25MB')
    sys.path.insert(0, str(project))
    from native_runner.tools.royaleapi_hog_il import parse_royaleapi_replay_html
    from native_runner.royaleapi_replay import resolve_native_card, RoyaleAPIReplayError
    def resolve(key, name):
        try: return resolve_native_card(key, name).card_id
        except RoyaleAPIReplayError: return None
    try:
        payload = parse_royaleapi_replay_html(normalize_saved_links(html), preserve_all_events=True)
    except (TypeError, KeyError, ValueError) as exc:
        raise ValueError('页面尚无完整回放数据；请先完成登录/验证并打开回放详情。' + str(exc)) from exc
    if payload['source']['replay_tag'] != tag: raise ValueError('页面数据与网址的回放编号不同，请等待页面完成加载')
    raw = html.encode('utf-8'); sha = hashlib.sha256(raw).hexdigest()
    path = Path(directory) / (tag + '-' + sha[:16] + '.html')
    parser = Path(project) / 'native_runner/tools/royaleapi_hog_il.py'
    source = convert(payload, source_path=path, source_bytes=raw, parser_digest=hashlib.sha256(parser.read_bytes()).hexdigest(),
                     card_ids=card_ids_from_html(normalize_saved_links(html), resolve))
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha: raise ValueError('已保存 HTML 被改动，不覆盖它')
    else:
        with path.open('xb') as f: f.write(raw)
    report = dict(schema='official-web-replay.browser-capture.v1', path=str(path.resolve()),
                  source_url=public_url, source_sha256=sha, replay_tag=tag,
                  retained_action_count=source['retained_action_count'], dropped_actions=source['dropped_actions'],
                  unresolved_base_card_ids=source['unresolved_base_card_ids'],
                  captured_at_utc=datetime.now(timezone.utc).isoformat(), network_requests_made=False)
    meta = path.with_suffix('.capture.json')
    if not meta.exists():
        with meta.open('x',encoding='utf-8') as f: json.dump(report, f, ensure_ascii=False, indent=2)
    return report
