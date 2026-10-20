"""Replay-only card resolver extracted from FirstLight (Apache-2.0).
Modified: public alias index loaded from a bundled JSON snapshot, not training/data directories.
"""
from __future__ import annotations
import json,re
from pathlib import Path
from dataclasses import dataclass
from functools import lru_cache
_FORM_SUFFIX=re.compile(r"-(?:ev\d+|hero)$",re.IGNORECASE)
ROYALAPI_CARD_KEY_IDS={'bandit': 26000046, 'barbarian-barrel': 28000015, 'dart-goblin': 26000040, 'elite-barbarians': 26000043, 'giant-snowball': 28000017, 'guards': 26000025, 'lumberjack': 26000035, 'royal-ghost': 26000050, 'rune-giant': 26000101, 'skeleton-barrel': 26000056, 'sparky': 26000033, 'spirit-empress': 28000025, 'void': 28000023}

class RoyaleAPIReplayError(RuntimeError):
    """Raised when a collected row cannot be rendered faithfully enough."""

@dataclass(frozen=True, slots=True)
class NativeCardInfo:
    card_id: int
    name: str
    kind: str
    aliases: tuple[str, ...]
    omit_from_starting_hand: bool = False

def _normalized_alias(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())

def base_card_key(value: object) -> str:
    return _FORM_SUFFIX.sub("", str(value or "").strip()).casefold()

def resolve_native_card(card_key: str, card_name: str | None = None) -> NativeCardInfo:
    by_id, aliases = _load_card_index()
    public_key = base_card_key(card_key)
    explicit = ROYALAPI_CARD_KEY_IDS.get(public_key)
    if explicit is not None:
        try:
            return by_id[explicit]
        except KeyError as error:
            raise RoyaleAPIReplayError(f"native catalog 缺少 {public_key} 对应卡牌 {explicit}") from error

    probes = (_normalized_alias(public_key), _normalized_alias(card_name))
    for probe in probes:
        if not probe:
            continue
        matches = aliases.get(probe, ())
        if len(matches) == 1:
            return by_id[matches[0]]
        if len(matches) > 1:
            raise RoyaleAPIReplayError(f"卡牌 {card_key!r} 在 native catalog 中不唯一：{matches}")
    fallback_probes: set[str] = set()
    for probe in probes:
        if not probe:
            continue
        fallback_probes.add(probe + "s")
        if probe.endswith("s"):
            fallback_probes.add(probe[:-1])
    matches = {card_id for probe in fallback_probes for card_id in aliases.get(probe, ())}
    if len(matches) == 1:
        return by_id[next(iter(matches))]
    raise RoyaleAPIReplayError(f"无法把 RoyaleAPI 卡牌 {card_key!r} ({card_name or '无名称'}) 映射到 native card ID")
@lru_cache(maxsize=1)
def _load_card_index():
    rows=json.loads(Path(__file__).with_name('card-aliases.json').read_text())
    by_id={};aliases={}
    for row in rows:
        row['aliases']=tuple(row['aliases']);info=NativeCardInfo(**row);by_id[info.card_id]=info
        for alias in info.aliases:aliases.setdefault(alias,[]).append(info.card_id)
    return by_id,{key:tuple(sorted(value)) for key,value in aliases.items()}
