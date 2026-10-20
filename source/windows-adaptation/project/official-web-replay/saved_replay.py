"""Local source selection, independent of native task ownership and success."""
import hashlib
import json
from pathlib import Path
import tempfile
import os


def remember(directory, html, source):
    directory = Path(directory).resolve()
    html = Path(html).resolve()
    if not html.is_relative_to(directory) or not html.is_file():
        raise ValueError('saved replay must be an owned local source')
    digest = hashlib.sha256(html.read_bytes()).hexdigest()
    if source['source_sha256'] != digest:
        raise ValueError('saved HTML/source hash differs')
    value = dict(path=str(html), source_sha256=digest,
                 replay_tag=source['replay_tag'], retained_action_count=source['retained_action_count'])
    fd, name = tempfile.mkstemp(prefix='saved-', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
        os.replace(name, directory/'saved-replay.json')
    finally:
        if os.path.exists(name): os.unlink(name)
    return value


def selected(directory, expected=None):
    directory = Path(directory).resolve()
    try:
        value = json.loads((directory/'saved-replay.json').read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    html = Path(value['path']).resolve()
    if (not html.is_relative_to(directory) or not html.is_file()
            or hashlib.sha256(html.read_bytes()).hexdigest() != value['source_sha256']):
        raise ValueError('已保存 HTML 发生变化，请重新导入')
    if expected is not None and expected != value['source_sha256']:
        raise ValueError('保存的回放已切换，未操作另一场回放')
    return value


def forget(directory, expected):
    if selected(directory, expected) is None:
        return
    # Remove only this selection index; keep original HTML, receipts and cache.
    (Path(directory)/'saved-replay.json').unlink()
