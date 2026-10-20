"""Reuse verified native inputs only when the ENTIRE parsed replay agrees.

HTML ads, login widgets and capture paths may change. No event, owner, position,
clock, form, level, tower, result or deck field is removed from this comparison.
Keep canonical evidence unchanged and record the new HTML as a separate alias.
"""
import hashlib
import json


def content_digest(source):
    if source.get('schema')!='official-web-replay.source.v1':
        raise ValueError('unsupported replay source')
    if source.get('dropped_actions')!=0 or source.get('retained_action_count')!=len(source['actions']):
        raise ValueError('incomplete source cannot reuse verified replay')
    ignored={'source_html','source_sha256','parser_sha256','execution_timing_offset_seconds'}
    content={key:value for key,value in source.items() if key not in ignored}
    return hashlib.sha256(json.dumps(content,ensure_ascii=False,sort_keys=True,
                                    separators=(',',':')).encode()).hexdigest()
