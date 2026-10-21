"""Full source import inside embedded Android Python; never executes HTML."""
import hashlib
import json
from pathlib import Path
import traceback
import re

from native_runner.tools.royaleapi_hog_il import parse_royaleapi_replay_html
from native_runner.royaleapi_replay import resolve_native_card, RoyaleAPIReplayError
from import_replay import card_ids_from_html, convert


def normalize_saved_links(text):
    # Browser Save Page makes same-site card links absolute. Normalize only
    # those hrefs for the existing parser; hash and retain original bytes.
    return re.sub(r'(?i)(\bhref\s*=\s*[\"\'])https://royaleapi\.com(?=/card/)',r'\1',text)


def run(source: Path, destination: Path):
    destination.mkdir(exist_ok=False)
    try:
        raw = source.read_bytes()
        if not 0 < len(raw) <= 25*1024*1024:
            raise ValueError('HTML size exceeds bounded input')
        text = normalize_saved_links(raw.decode('utf-8', errors='strict'))
        payload = parse_royaleapi_replay_html(text, preserve_all_events=True)

        def resolve(key, name):
            try: return resolve_native_card(key, name).card_id
            except RoyaleAPIReplayError: return None

        parser = Path(__file__).parent/'native_runner/tools/royaleapi_hog_il.py'
        document = convert(payload, source_path=source, source_bytes=raw,
                           parser_digest=hashlib.sha256(parser.read_bytes()).hexdigest(),
                           card_ids=card_ids_from_html(text, resolve))
        document['processing_location'] = 'android-embedded-python'
        document['saved_link_normalization']='royaleapi-https-card-href-only-v1'
        document['desktop_backend_used'] = False
        with (destination/'source.json').open('x', encoding='utf-8') as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
        summary = dict(state='source_imported', schema='royale-replay.android-full-import.v1',
                       processing_location='android-embedded-python', desktop_backend_used=False,
                       replay_tag=document['replay_tag'], source_sha256=document['source_sha256'],
                       retained_events=document['retained_action_count'], dropped_actions=document['dropped_actions'],
                       requirements=document['requirements'], unresolved_base_card_ids=document['unresolved_base_card_ids'],
                       source_duration_seconds=document['source_duration_seconds'], native_calls=False,
                       standalone_playback_ready=False)
        with (destination/'result.json').open('x', encoding='utf-8') as stream:
            json.dump(summary, stream, ensure_ascii=False, indent=2)
    except Exception:
        with (destination/'error.txt').open('x', encoding='utf-8') as stream:
            stream.write(traceback.format_exc())
        raise
