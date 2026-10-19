"""Import RoyaleAPI expert replays for Hog-cycle imitation learning.

RoyaleAPI exports are intentionally treated as user-provided files.  The
public site can identify players and decks, but a battle replay's action
timeline is login-gated.  This tool therefore never scrapes around that gate:
it accepts the JSON/JSONL/Parquet file downloaded by the user, filters it, and
writes the repository's ``royaleapi-battle-replay.v1`` Parquet dataset.

The output is suitable for ``native_runner.training.v4.cache_builder``.  A
row is accepted only when it contains source action events and an unambiguous
RoyaleAPI true-side marker; battle-log-only records are reported and skipped.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import dataclass
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import parse_qs, urlparse

FIRST_POLICY_DECISION_TICK = 90  # original expert cutoff; playback uses preserve_all_events=True


SCHEMA = "royaleapi-hog-imitation-source.v1"
PAYLOAD_SCHEMA = "royaleapi-battle-replay.v1"
DEFAULT_REGISTRY = Path(__file__).resolve().parents[2] / "configs" / "royaleapi_hog_players.json"
_TAG_RE = re.compile(r"^[0-9A-Z]{6,16}$")


@dataclass(frozen=True, slots=True)
class PlayerSource:
    name: str
    tag: str
    rank: int | None
    avg_elixir: float | None
    url: str


def normalize_tag(value: object) -> str:
    return str(value or "").strip().upper().removeprefix("#")


def load_registry(path: Path) -> tuple[PlayerSource, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("players") if isinstance(payload, Mapping) else None
    if not isinstance(rows, list):
        raise ValueError(f"player registry has no players array: {path}")
    result: list[PlayerSource] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ValueError("player registry row is not an object")
        tag = normalize_tag(raw.get("tag"))
        if not _TAG_RE.fullmatch(tag):
            raise ValueError(f"invalid player tag in registry: {tag!r}")
        if tag in seen:
            raise ValueError(f"duplicate player tag in registry: {tag}")
        seen.add(tag)
        rank = raw.get("rank")
        avg = raw.get("avg_elixir")
        result.append(
            PlayerSource(
                name=str(raw.get("name") or tag),
                tag=tag,
                rank=int(rank) if rank is not None else None,
                avg_elixir=float(avg) if avg is not None else None,
                url=str(raw.get("url") or f"https://royaleapi.com/player/{tag}"),
            )
        )
    return tuple(result)


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _payload_like(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    if value.get("schema_version") == PAYLOAD_SCHEMA:
        return True
    return isinstance(value.get("events"), list) and isinstance(value.get("battle"), Mapping)


def iter_payloads(value: object) -> Iterable[dict[str, Any]]:
    """Yield payloads from common RoyaleAPI download wrappers."""

    if _payload_like(value):
        yield dict(value)
        return
    if isinstance(value, list):
        for item in value:
            yield from iter_payloads(item)
        return
    if not isinstance(value, Mapping):
        return
    # Downloaders commonly wrap rows as battles/replays/data/results, or as
    # payload_json strings.  Keep this permissive while never inventing an
    # action timeline from a battle-log summary.
    for key in ("payload", "payload_json", "replay", "replays", "battles", "data", "results", "rows"):
        child = value.get(key)
        if isinstance(child, str) and key == "payload_json":
            try:
                child = json.loads(child)
            except json.JSONDecodeError:
                continue
        if child is not None:
            yield from iter_payloads(child)


def _players(payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    battle = payload.get("battle")
    if not isinstance(battle, Mapping):
        return ()
    result: list[Mapping[str, Any]] = []
    for side in ("team", "opponent"):
        side_payload = battle.get(side)
        if not isinstance(side_payload, Mapping):
            continue
        rows = side_payload.get("players")
        if isinstance(rows, list):
            result.extend(row for row in rows if isinstance(row, Mapping))
    return tuple(result)


def _player_tags(payload: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(tag for tag in (normalize_tag(row.get("tag")) for row in _players(payload)) if tag)


def _deck_cards(player: Mapping[str, Any]) -> tuple[str, ...]:
    deck = player.get("deck")
    if not isinstance(deck, list):
        return ()
    result: list[str] = []
    for card in deck:
        if not isinstance(card, Mapping):
            continue
        key = card.get("card_key") or card.get("key") or card.get("cardKey")
        if key:
            result.append(str(key).strip().lower())
    return tuple(result)


def _avg_elixir(player: Mapping[str, Any]) -> float | None:
    for key in ("avg_elixir", "average_elixir", "avgElixir"):
        value = player.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    cards = player.get("deck")
    if not isinstance(cards, list) or len(cards) != 8:
        return None
    costs = [card.get("elixir") for card in cards if isinstance(card, Mapping)]
    if len(costs) != 8 or not all(isinstance(cost, (int, float)) for cost in costs):
        return None
    return sum(float(cost) for cost in costs) / 8.0


def _event_has_source_timeline(payload: Mapping[str, Any]) -> tuple[bool, str]:
    events = payload.get("events")
    if not isinstance(events, list):
        return False, "missing_action_events"
    actions = [event for event in events if isinstance(event, Mapping) and event.get("kind") in {"play_card", "activate_ability"}]
    if not actions:
        return False, "no_action_events"
    markers = {
        event.get("source_fields", {}).get("data_i")
        for event in actions
        if isinstance(event.get("source_fields"), Mapping)
    }
    if markers != {0, 1} and markers != {0} and markers != {1}:
        return False, "missing_or_mixed_data_i"
    if not markers:
        return False, "missing_or_mixed_data_i"
    return True, "accepted"


def _replay_tag(payload: Mapping[str, Any], ordinal: int) -> str:
    source = payload.get("source")
    if isinstance(source, Mapping) and source.get("replay_tag"):
        return str(source["replay_tag"])
    for key in ("replay_tag", "replayTag", "battle_tag", "battleTag", "id"):
        if payload.get(key):
            return str(payload[key])
    return "royaleapi-import-" + hashlib.sha256(_canonical(payload)).hexdigest()[:20]


def _source_url(payload: Mapping[str, Any]) -> str | None:
    source = payload.get("source")
    if isinstance(source, Mapping):
        value = source.get("url") or source.get("replay_url")
        return str(value) if value else None
    return None


def _deck_class(player: Mapping[str, Any]) -> tuple[bool, str, float | None]:
    cards = set(_deck_cards(player))
    if "hog-rider" not in cards:
        return False, "not_hog", _avg_elixir(player)
    avg = _avg_elixir(player)
    if avg is None:
        return True, "hog_unscored", None
    if avg <= 3.0:
        return True, "hog_cycle_26_28", avg
    if avg <= 3.2:
        return True, "hog_cycle_slow", avg
    return False, "hog_too_heavy", avg


def _deck_class_with_limit(player: Mapping[str, Any], max_avg_elixir: float) -> tuple[bool, str, float | None]:
    is_hog, deck_class, avg = _deck_class(player)
    if not is_hog or avg is None:
        return is_hog, deck_class, avg
    if avg <= max_avg_elixir:
        return True, deck_class, avg
    return False, "avg_elixir_above_limit", avg


def _native_replay_eligibility_error(payload: Mapping[str, Any]) -> str | None:
    """Reject expert rows the installed native replay schema cannot represent."""

    from native_runner.royaleapi_replay import RoyaleAPIReplayError, _tower_troop, resolve_native_card

    battle = payload.get("battle")
    if not isinstance(battle, Mapping):
        return "missing_battle"
    for side in ("team", "opponent"):
        side_payload = battle.get(side)
        players = side_payload.get("players") if isinstance(side_payload, Mapping) else None
        if not isinstance(players, list) or not players:
            return f"missing_{side}_players"
        for player in players:
            if not isinstance(player, Mapping):
                return f"invalid_{side}_player"
            deck = player.get("deck")
            cards = deck if isinstance(deck, list) else ()
            if len(cards) != 8:
                return f"incomplete_{side}_deck"
            for card in cards:
                if not isinstance(card, Mapping):
                    return f"invalid_{side}_deck_card"
                key = str(card.get("card_key") or card.get("key") or card.get("cardKey") or "").strip()
                name = str(card.get("name") or "").strip() or None
                if not key:
                    return f"missing_{side}_deck_card_key"
                try:
                    resolve_native_card(key, name)
                except RoyaleAPIReplayError:
                    return f"unsupported_native_card:{key}"
            try:
                _tower_troop(player, side)
            except RoyaleAPIReplayError:
                tower = player.get("tower_card")
                key = str(tower.get("card_key") or "unknown") if isinstance(tower, Mapping) else "unknown"
                return f"unsupported_native_tower:{key}"
    return None


def select_payloads(
    payloads: Iterable[Mapping[str, Any]],
    sources: Sequence[PlayerSource],
    *,
    max_avg_elixir: float = 3.0,
    allow_unscored: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, int], list[dict[str, Any]]]:
    source_by_tag = {source.tag: source for source in sources}
    selected: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    audit: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ordinal, raw in enumerate(payloads):
        payload = dict(raw)
        tag = _replay_tag(payload, ordinal)
        if tag in seen:
            rejected["duplicate_replay_tag"] += 1
            continue
        seen.add(tag)
        participant_tags = set(_player_tags(payload))
        matched = [source_by_tag[item] for item in participant_tags if item in source_by_tag]
        if not matched:
            rejected["not_from_selected_player"] += 1
            continue
        expert = next((player for player in _players(payload) if normalize_tag(player.get("tag")) in source_by_tag), None)
        if expert is None:
            rejected["selected_player_missing"] += 1
            continue
        is_hog, deck_class, avg = _deck_class_with_limit(expert, max_avg_elixir)
        if not is_hog:
            rejected[deck_class] += 1
            continue
        if avg is not None and avg > max_avg_elixir:
            rejected["avg_elixir_above_limit"] += 1
            continue
        if avg is None and not allow_unscored:
            rejected["unscored_deck"] += 1
            continue
        native_error = _native_replay_eligibility_error(payload)
        if native_error is not None:
            rejected[native_error] += 1
            audit.append({"replay_tag": tag, "status": "rejected", "reason": native_error})
            continue
        has_timeline, timeline_reason = _event_has_source_timeline(payload)
        if not has_timeline:
            rejected[timeline_reason] += 1
            audit.append({"replay_tag": tag, "status": "rejected", "reason": timeline_reason})
            continue
        source = dict(payload.get("source") or {})
        source.update(
            {
                "replay_tag": tag,
                "royaleapi_source_player_tag": normalize_tag(expert.get("tag")),
                "royaleapi_source_player_name": str(expert.get("name") or matched[0].name),
                "royaleapi_source_player_rank": matched[0].rank,
                "royaleapi_source_player_url": matched[0].url,
                "royaleapi_hog_deck_class": deck_class,
                "royaleapi_hog_avg_elixir": avg,
                "royaleapi_import_schema": SCHEMA,
            }
        )
        payload["schema_version"] = PAYLOAD_SCHEMA
        payload["source"] = source
        selected.append(payload)
        audit.append(
            {
                "replay_tag": tag,
                "status": "selected",
                "player_tag": normalize_tag(expert.get("tag")),
                "player_name": str(expert.get("name") or matched[0].name),
                "deck_class": deck_class,
                "avg_elixir": avg,
                "source_url": _source_url(payload),
            }
        )
    return selected, dict(rejected), audit


def _read_input(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        return [parse_royaleapi_replay_html(path.read_text(encoding="utf-8"))]
    if path.name == "-":
        values = [json.load(sys.stdin)]
        return [payload for value in values for payload in iter_payloads(value)]
    if suffix in {".jsonl", ".ndjson"}:
        values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    elif suffix == ".parquet":
        import pyarrow.parquet as parquet

        table = parquet.read_table(path, columns=["payload_json"])
        values = [json.loads(str(raw)) for raw in table.column("payload_json").to_pylist()]
    else:
        values = [json.loads(path.read_text(encoding="utf-8"))]
    return [payload for value in values for payload in iter_payloads(value)]


class _ReplayHTMLParser(HTMLParser):
    """Extract the replay markers rendered by RoyaleAPI's replay page.

    The page intentionally exposes the replay twice: card icons on the
    timeline carry ``data-t``/``data-s``, while arena markers carry those same
    fields plus ``data-x``/``data-y``/``data-c``/``data-i``.  Only the latter
    are used for actions because they preserve the deployment target.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.replay_tag: str | None = None
        self.events: list[dict[str, Any]] = []
        self.decks: dict[str, list[str]] = {"blue": [], "red": []}
        self.player_links: list[tuple[str, str]] = []
        self._anchor: tuple[str, list[str]] | None = None
        self._result: str | None = None
        self.battle_type: str | None = None
        self._in_win_loss = False
        self._duration_seconds: float | None = None
        self.tower_health: list[dict[str, int]] = []

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {key: value or "" for key, value in attrs}

    @staticmethod
    def _event_side(value: str | None) -> str:
        # Arena markers use t/o; timeline ability icons use blue/red.
        # This is source identity, independent of data-i/display rotation.
        side = {"t": "team", "blue": "team", "o": "opponent", "red": "opponent"}.get(value)
        if side is None:
            raise ValueError(f"RoyaleAPI action has unknown data-s marker {value!r}")
        return side

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = self._attrs(attrs)
        classes = set(values.get("class", "").split())
        if "battle_list_battle" in classes and values.get("data-battle-type"):
            self.battle_type = values["data-battle-type"].strip().lower()
        if "hp-popup" in classes:
            try:
                health = {
                    key: int(values[f"data-{key}"])
                    for key in ("king", "princess0", "princess1", "total")
                }
            except (KeyError, TypeError, ValueError):
                pass
            else:
                if all(value >= 0 for value in health.values()):
                    self.tower_health.append(health)
        if "battle_replay" in classes and values.get("data-tag"):
            self.replay_tag = values["data-tag"].strip().removeprefix("#")
        if tag == "a":
            href = values.get("href", "")
            match = re.search(r"/player/([0-9A-Z]{6,16})/battles", href, re.IGNORECASE)
            if match:
                self._anchor = (normalize_tag(match.group(1)), [])
        if "win_loss" in classes:
            self._in_win_loss = True
        if tag == "img" and values.get("data-card"):
            card = values["data-card"].strip().lower()
            side = values.get("data-s", "")
            if not values.get("data-t") and side in self.decks and card not in self.decks[side]:
                self.decks[side].append(card)
        if values.get("data-ability") not in {"", "0", None} and values.get("data-t") and values.get("data-s"):
            # RoyaleAPI renders hero abilities as public timeline markers with
            # data-x/data-y="None" and data-c="_invalid". They have no board
            # target, but their owner and command tick are authoritative; the
            # replay adapter resolves the matching ready hero instance.
            side = self._event_side(values.get("data-s"))
            try:
                data_i_value = values.get("data-i", "")
                event = {
                    "kind": "activate_ability",
                    "side": side,
                    "replay_tick_20hz": int(values["data-t"]),
                    "replay_time_cs": int(values["data-t"]) * 5,
                    "source_index": len(self.events),
                    "source_fields": {
                        "data_i": int(data_i_value) if data_i_value.lstrip("-").isdigit() else data_i_value,
                        "data_t": int(values["data-t"]),
                        "data_s": values.get("data-s"),
                        "data_ability": values.get("data-ability"),
                    },
                }
                self.events.append(event)
            except (TypeError, ValueError):
                return
            return
        if values.get("data-x") and values.get("data-y") and values.get("data-c") and values.get("data-t"):
            # The positionless _invalid arena marker is a second rendering of
            # a timeline ability icon, not a card with a fabricated position.
            if values["data-x"] == "None" and values["data-y"] == "None":
                return
            side = self._event_side(values.get("data-s"))
            try:
                world_x = int(values["data-x"])
                world_y = int(values["data-y"])
                grid_x = world_x // 1000
                grid_y = world_y // 1000
                if not (0 <= world_x < 18000 and 0 <= world_y < 32000):
                    raise ValueError("replay coordinate outside native arena bounds")
                event = {
                    "kind": "activate_ability" if values.get("data-ability") not in {"", "0", None} else "play_card",
                    "side": side,
                    "card_key": values["data-c"].strip().lower(),
                    # RoyaleAPI's data-t is already a 20 Hz replay tick. Keep
                    # that source clock intact; dividing by five compresses a
                    # full ~3-minute replay to ~35 seconds and makes plays
                    # arrive before their elixir/hand-cycle state is possible.
                    "replay_tick_20hz": int(values["data-t"]),
                    "replay_time_cs": int(values["data-t"]) * 5,
                    "source_index": len(self.events),
                    "position": {"x": world_x, "y": world_y},
                    "coordinates": {
                        "inside_18x32_arena": True,
                        "grid_cell_floor": {"x": grid_x, "y": grid_y},
                        "subcell_offset_from_floor_center": {
                            "x": world_x / 1000.0 - (grid_x + 0.5),
                            "y": world_y / 1000.0 - (grid_y + 0.5),
                        },
                    },
                    "source_fields": {
                        "data_i": int(values["data-i"]) if values.get("data-i", "").lstrip("-").isdigit() else values.get("data-i"),
                        "data_x": int(values["data-x"]),
                        "data_y": int(values["data-y"]),
                        "data_t": int(values["data-t"]),
                        "data_s": values.get("data-s"),
                        "data_c": values["data-c"],
                    },
                }
                self.events.append(event)
            except (TypeError, ValueError):
                return
        if "end_time" in classes:
            self._anchor = ("__duration__", [])

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if self._anchor is not None:
            self._anchor[1].append(text)
        if self._in_win_loss:
            if text.lower() in {"victory", "defeat", "draw", "tie"}:
                self._result = {"victory": "victory", "defeat": "defeat", "draw": "draw", "tie": "draw"}[text.lower()]
            self._in_win_loss = False
        if re.fullmatch(r"\d+:\d{2}", text) and self._anchor and self._anchor[0] == "__duration__":
            minutes, seconds = text.split(":")
            self._duration_seconds = int(minutes) * 60 + int(seconds)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._anchor is not None and self._anchor[0] != "__duration__":
            self.player_links.append((self._anchor[0], " ".join(self._anchor[1]).strip()))
            self._anchor = None


def parse_royaleapi_replay_html(
    html: str, *, replay_url: str | None = None, preserve_all_events: bool = False
) -> dict[str, Any]:
    parser = _ReplayHTMLParser()
    parser.feed(html)
    parser.close()
    replay_tag = parser.replay_tag
    if not replay_tag and replay_url:
        replay_tag = normalize_tag(parse_qs(urlparse(replay_url).query).get("tag", [""])[0])
    if not replay_tag:
        raise ValueError("RoyaleAPI replay HTML has no battle_replay data-tag")
    if not parser.events:
        raise ValueError(f"RoyaleAPI replay {replay_tag} has no action markers")
    links: list[tuple[str, str]] = []
    seen_tags: set[str] = set()
    for tag, name in parser.player_links:
        if tag not in seen_tags:
            seen_tags.add(tag)
            links.append((tag, name or tag))
    team_tag, team_name = links[0] if links else ("", "team")
    opponent_tag, opponent_name = links[1] if len(links) > 1 else ("", "opponent")
    if replay_url:
        query = parse_qs(urlparse(replay_url).query)
        team_tag = normalize_tag(query.get("team_tags", [team_tag])[0]) or team_tag
        opponent_tag = normalize_tag(query.get("opponent_tags", [opponent_tag])[0]) or opponent_tag
    source_data_i = {
        event.get("source_fields", {}).get("data_i")
        for event in parser.events
        if event.get("source_fields", {}).get("data_i") in (0, 1)
    }
    if len(source_data_i) != 1:
        raise ValueError(f"RoyaleAPI replay {replay_tag} has mixed or missing data-i markers")
    # Ability arena markers often omit data-i even though the card markers in
    # this replay carry the constant true-side flag. Attach that replay-level
    # flag so every retained event uses one validated side mapping.
    source_data_i_value = next(iter(source_data_i))
    for event in parser.events:
        fields = event.get("source_fields")
        if isinstance(fields, dict) and fields.get("data_i") not in (0, 1):
            fields["data_i"] = source_data_i_value
    duration = parser._duration_seconds or max(int(event["replay_time_cs"]) for event in parser.events) / 100.0
    result = parser._result or "unknown"
    outcome = {"victory": "win", "defeat": "loss", "draw": "draw"}.get(result, "unknown")
    profile_decks: list[dict[str, int]] = []
    deck_grid_starts = list(re.finditer(r'<div class="[^"]*\bpadded\b[^"]*\bgrid\b[^"]*" id="deck_[^"]+">', html))
    for index, start in enumerate(deck_grid_starts[:2]):
        end = deck_grid_starts[index + 1].start() if index + 1 < len(deck_grid_starts) else len(html)
        region = html[start.end():end]
        levels: dict[str, int] = {}
        for match in re.finditer(
            r'<img\b(?=[^>]*\bdata-card-key="([^"]+)")[^>]*>.*?'
            r'<div class="[^"]*card-level[^"]*">.*?(\d+)',
            region,
            re.IGNORECASE | re.DOTALL,
        ):
            levels[match.group(1).strip().lower()] = int(match.group(2))
        profile_decks.append(levels)

    def deck_rows(side: str) -> list[dict[str, Any]]:
        cards = parser.decks[side]
        profile_index = 0 if side == "blue" else 1
        profile = profile_decks[profile_index] if profile_index < len(profile_decks) else {}
        profile_levels_by_base: dict[str, set[int]] = {}
        profile_keys_by_base: dict[str, set[str]] = {}
        for profile_key, level in profile.items():
            base_key = re.sub(r"-(?:ev\d+|hero)$", "", profile_key, flags=re.IGNORECASE)
            profile_levels_by_base.setdefault(base_key, set()).add(int(level))
            profile_keys_by_base.setdefault(base_key, set()).add(profile_key)

        def equipped_card_key(card: str) -> str:
            # Timeline/action markers use the base card key, but the deck
            # profile carries the equipped form (for example ``-ev1`` or
            # ``-hero``). Keep that form in the deck row: the replay adapter
            # strips it for card-ID matching and independently uses the suffix
            # to configure form availability and hero-ability bindings.
            candidates = profile_keys_by_base.get(card, set())
            return next(iter(candidates)) if len(candidates) == 1 else card

        def card_level(card: str) -> int | None:
            exact = profile.get(card)
            if exact is not None:
                return int(exact)
            # Replay action markers usually use the base card key, while the
            # deck profile names the equipped Evo/Hero form (e.g. hog-rider
            # versus hog-rider-hero). The level belongs to the base card.
            candidates = profile_levels_by_base.get(card, set())
            return next(iter(candidates)) if len(candidates) == 1 else None

        return [
            {
                "card_key": equipped_card_key(card),
                **({"level": level} if (level := card_level(card)) is not None else {}),
            }
            for card in cards
        ]

    battle = {
        "requested_player_tag": team_tag,
        "result": result,
        "team": {"players": [{"name": team_name, "tag": team_tag, "deck": deck_rows("blue")}]},
        "opponent": {"players": [{"name": opponent_name, "tag": opponent_tag, "deck": deck_rows("red")}]},
    }
    if parser.battle_type:
        battle["game_mode"] = parser.battle_type
    tower_cards = re.findall(
        r'<a\s+href="/card/([^"?#]+)"[^>]*>\s*<div class="deck_tower_card__container">.*?'
        r'<div class="level">.*?<div>.*?Lvl(?:\s*</span>)?\s*(\d+)\s*</div>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if len(tower_cards) >= 2:
        for side, value in zip(("team", "opponent"), tower_cards[:2]):
            battle[side]["players"][0]["tower_card"] = {
                "card_key": value[0].strip().lower(),
                "level": int(value[1]),
            }
    if len(parser.tower_health) == 2:
        # On the replay page the first stat card is the selected/team player,
        # followed by their opponent, matching the URL's team_tags order.
        battle["team"]["tower_health"] = parser.tower_health[0]
        battle["opponent"]["tower_health"] = parser.tower_health[1]
    events = sorted(
        parser.events,
        key=lambda event: (int(event["replay_time_cs"]), int(event["source_fields"].get("data_i") or 0)),
    )
    # Playback must retain the entire source timeline. Keep the training
    # default unchanged; its decision cutoff is not a replay-engine rule.
    cutoff = 0 if preserve_all_events else FIRST_POLICY_DECISION_TICK
    pre_policy_events = sum(int(event["replay_tick_20hz"]) < cutoff for event in events)
    events = [event for event in events if int(event["replay_tick_20hz"]) >= cutoff]
    if not events:
        raise ValueError(f"RoyaleAPI replay {replay_tag} has no action markers after the first policy decision")
    return {
        "schema_version": PAYLOAD_SCHEMA,
        "source": {
            "replay_tag": replay_tag,
            "url": replay_url,
            "html_extractor": "royaleapi-replay-dom.v1",
            "source_data_i": next(iter(source_data_i)),
            "training_first_policy_decision_tick": cutoff,
            "all_source_events_preserved": preserve_all_events,
            "dropped_pre_policy_event_count": pre_policy_events,
        },
        "battle": battle,
        "replay": {"duration": {"timeline_seconds": duration}, "outcome": outcome},
        "events": events,
    }


def _csv_card_rows(row: Mapping[str, str], prefix: str = "team_0") -> list[dict[str, object]]:
    cards: list[dict[str, object]] = []
    for index in range(8):
        name = str(row.get(f"{prefix}_cards_{index}_name") or "").strip()
        if not name:
            continue
        cost = row.get(f"{prefix}_cards_{index}_elixirCost")
        try:
            elixir = float(cost) if cost not in (None, "") else None
        except ValueError:
            elixir = None
        cards.append(
            {
                "name": name,
                "id": row.get(f"{prefix}_cards_{index}_id"),
                "elixir": elixir,
            }
        )
    return cards


def _csv_queue_rows(path: Path, *, selected_tags: set[str], max_avg_elixir: float) -> tuple[list[dict[str, object]], Counter[str]]:
    rows: list[dict[str, object]] = []
    rejected: Counter[str] = Counter()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            player_tag = normalize_tag(raw.get("team_0_tag"))
            if player_tag not in selected_tags:
                rejected["csv_player_not_in_registry"] += 1
                continue
            replay_tag = str(raw.get("replayTag") or "").strip().removeprefix("#")
            if not replay_tag:
                rejected["csv_missing_replay_tag"] += 1
                continue
            cards = _csv_card_rows(raw)
            names = {str(card["name"]) for card in cards}
            if "Hog Rider" not in names:
                rejected["csv_not_hog"] += 1
                continue
            costs = [float(card["elixir"]) for card in cards if isinstance(card.get("elixir"), (int, float))]
            avg = sum(costs) / len(costs) if len(costs) == 8 else None
            if avg is None:
                rejected["csv_unscored_deck"] += 1
                continue
            if avg > max_avg_elixir:
                rejected["csv_avg_elixir_above_limit"] += 1
                continue
            opponent_tag = normalize_tag(raw.get("opponent_0_tag"))
            def _number(value: object) -> int:
                try:
                    return int(float(str(value or "0").strip() or "0"))
                except (TypeError, ValueError):
                    return 0

            team_crowns = _number(raw.get("team_0_crowns"))
            opponent_crowns = _number(raw.get("opponent_0_crowns"))
            result = "win" if team_crowns > opponent_crowns else "draw" if team_crowns == opponent_crowns else "loss"
            rows.append(
                {
                    "replay_tag": replay_tag,
                    "player_tag": player_tag,
                    "player_name": str(raw.get("team_0_name") or player_tag),
                    "opponent_tag": opponent_tag,
                    "opponent_name": str(raw.get("opponent_0_name") or opponent_tag),
                    "battle_time": raw.get("battleTime"),
                    "battle_type": raw.get("type"),
                    "result": result,
                    "trophy_change": raw.get("team_0_trophyChange"),
                    "crowns": team_crowns,
                    "avg_elixir": avg,
                    "deck": cards,
                    "source_csv": str(path.resolve()),
                    "replay_url": (
                        f"https://royaleapi.com/replay?tag={replay_tag}"
                        f"&team_tags={player_tag}&opponent_tags={opponent_tag}"
                        f"&team_crowns={raw.get('team_0_crowns') or 0}"
                        f"&opponent_crowns={raw.get('opponent_0_crowns') or 0}"
                    ),
                    "action_timeline_available": False,
                }
            )
    return rows, rejected


def build_replay_queue(
    csv_paths: Sequence[Path], sources: Sequence[PlayerSource], *, max_avg_elixir: float = 3.0
) -> tuple[list[dict[str, object]], dict[str, int]]:
    selected_tags = {source.tag for source in sources}
    queue: list[dict[str, object]] = []
    rejected: Counter[str] = Counter()
    seen: set[str] = set()
    for path in csv_paths:
        rows, reasons = _csv_queue_rows(path, selected_tags=selected_tags, max_avg_elixir=max_avg_elixir)
        rejected.update(reasons)
        for row in rows:
            tag = str(row["replay_tag"])
            if tag in seen:
                rejected["csv_duplicate_replay_tag"] += 1
                continue
            seen.add(tag)
            queue.append(row)
    queue.sort(key=lambda row: (str(row.get("battle_time") or ""), str(row["replay_tag"])), reverse=True)
    return queue, dict(rejected)


def _tags(payload: Mapping[str, Any], side: str) -> list[str]:
    battle = payload.get("battle")
    side_payload = battle.get(side) if isinstance(battle, Mapping) else None
    players = side_payload.get("players") if isinstance(side_payload, Mapping) else None
    return [normalize_tag(row.get("tag")) for row in players or () if isinstance(row, Mapping) and row.get("tag")]


def write_dataset(output: Path, payloads: Sequence[Mapping[str, Any]], manifest: Mapping[str, Any]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as parquet

    replay_dir = output / "replays"
    replay_dir.mkdir(parents=True, exist_ok=False)
    rows = []
    for index, payload in enumerate(payloads):
        tag = _replay_tag(payload, index)
        battle = payload.get("battle") if isinstance(payload.get("battle"), Mapping) else {}
        rows.append(
            {
                "replay_tag": tag,
                "requested_player_tag": normalize_tag(battle.get("requested_player_tag")),
                "team_tags": _tags(payload, "team"),
                "opponent_tags": _tags(payload, "opponent"),
                "played_at_utc": battle.get("played_at_utc"),
                "played_at_local": battle.get("played_at_local"),
                "payload_json": json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            }
        )
    parquet.write_table(pa.Table.from_pylist(rows), replay_dir / "part-000000.parquet")
    (output / "manifest.json").write_text(json.dumps(dict(manifest), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "train-tags.txt").write_text("".join(f"{row['replay_tag']}\n" for row in rows), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", required=True, help="RoyaleAPI downloaded JSON/JSONL/Parquet")
    parser.add_argument("--output", type=Path, help="new action-timeline dataset directory")
    parser.add_argument("--queue-output", type=Path, help="write a filtered replay URL/Tag queue from CSV battle logs")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--player-tag", action="append", default=[], help="override registry and select one or more tags")
    parser.add_argument("--max-avg-elixir", type=float, default=3.0)
    parser.add_argument("--allow-unscored", action="store_true", help="accept Hog decks with no elixir metadata")
    args = parser.parse_args()
    if args.output is not None and args.output.exists():
        raise FileExistsError(f"refusing to overwrite dataset: {args.output}")
    registry = load_registry(args.registry)
    if args.player_tag:
        requested = {normalize_tag(tag) for tag in args.player_tag}
        registry = tuple(source for source in registry if source.tag in requested)
        if requested != {source.tag for source in registry}:
            raise ValueError(f"requested player tag is absent from registry: {sorted(requested - {source.tag for source in registry})}")
    csv_inputs = tuple(path for path in args.input if path.suffix.lower() == ".csv")
    if csv_inputs:
        queue, rejected = build_replay_queue(csv_inputs, registry, max_avg_elixir=args.max_avg_elixir)
        if args.queue_output is None:
            raise ValueError("CSV battle logs contain no action timeline; pass --queue-output to write a replay queue")
        if args.queue_output.exists():
            raise FileExistsError(f"refusing to overwrite queue: {args.queue_output}")
        args.queue_output.parent.mkdir(parents=True, exist_ok=True)
        args.queue_output.write_text(
            json.dumps(
                {
                    "schema": "royaleapi-hog-replay-queue.v1",
                    "players": [source.tag for source in registry],
                    "filters": {"max_avg_elixir": args.max_avg_elixir},
                    "source_csvs": [str(path.resolve()) for path in csv_inputs],
                    "selected_replays": len(queue),
                    "rejected": rejected,
                    "action_timeline_available": False,
                    "rows": queue,
                    "next_step": "Open replay_url while logged in and obtain the Battle Replay action export; CSV rows alone are not trainable expert trajectories.",
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"queue_output": str(args.queue_output.resolve()), "selected_replays": len(queue), "rejected": rejected}, ensure_ascii=False, sort_keys=True))
        return
    if args.output is None:
        raise ValueError("--output is required for action-timeline JSON/JSONL/Parquet imports")
    raw_payloads = [payload for path in args.input for payload in _read_input(path)]
    selected, rejected, audit = select_payloads(
        raw_payloads, registry, max_avg_elixir=args.max_avg_elixir, allow_unscored=args.allow_unscored
    )
    if not selected:
        raise RuntimeError(
            "no expert replay selected; battle-log summaries do not contain action events, "
            "or the download is not from a selected Hog player"
        )
    manifest = {
        "schema": SCHEMA,
        "payload_schema": PAYLOAD_SCHEMA,
        "players": [
            {"name": source.name, "tag": source.tag, "rank": source.rank, "avg_elixir": source.avg_elixir, "url": source.url}
            for source in registry
        ],
        "input_files": [{"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in args.input],
        "filters": {"max_avg_elixir": args.max_avg_elixir, "allow_unscored": args.allow_unscored},
        "selected_replays": len(selected),
        "rejected": rejected,
        "audit": audit,
        "action_timeline_required": True,
        "note": "Only user-downloaded RoyaleAPI replay action exports are accepted; no login bypass or timeline synthesis.",
    }
    write_dataset(args.output, selected, manifest)
    print(json.dumps({"output": str(args.output.resolve()), "selected_replays": len(selected), "rejected": rejected}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
