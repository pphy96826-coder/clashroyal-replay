"""Global replay command delay, separate from the immutable HTML clock.

All console/manual/browser imports use the same absolute delay. Historical
per-match calibration records are not added to it and cannot override it.
"""
import argparse
import hashlib
import json
from pathlib import Path
from timing_experiment import shift

POLICY = Path(__file__).with_name('timing-overrides.json')
GLOBAL_DELAY_TICKS = 20


def offset_for(replay_tag, path=POLICY):
    if not path.exists():
        return GLOBAL_DELAY_TICKS
    data = json.loads(path.read_text())
    if data.get('schema') != 'official-web-replay.timing-overrides.v1':
        raise ValueError('invalid explicit timing policy')
    # Keep the tag argument for existing callers, but never restrict the
    # global rule to a known tag or compound an old per-match correction.
    ticks = data.get('default_offset_ticks', GLOBAL_DELAY_TICKS)
    if type(ticks) is not int or not 0 <= ticks <= 200:
        raise ValueError('unsupported global timing offset')
    return ticks


def recipe_for(base_recipe, ticks):
    if not ticks:
        return base_recipe
    return hashlib.sha256(json.dumps({
        'base_recipe': base_recipe, 'offset_ticks': ticks,
        'policy_code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'shift_code_sha256': hashlib.sha256(Path(__file__).with_name('timing_experiment.py').read_bytes()).hexdigest(),
    }, sort_keys=True).encode()).hexdigest()


def apply_offset(preparation, ticks):
    if 'execution_timing' in preparation:
        raise ValueError('global command delay already applied; never compound it')
    if not ticks:
        return preparation
    result = shift(preparation, ticks)
    result.pop('timing_experiment')
    result['execution_timing'] = {
        'offset_ticks': ticks, 'offset_seconds': ticks / 20,
        'scope': 'global-all-imported-replays',
        'original_html_clock_preserved': True,
        'initialization_and_terminal_rules_unchanged': True,
        'exact_result_verified': False,
    }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preparation', type=Path, required=True)
    parser.add_argument('--offset-ticks', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = apply_offset(json.loads(args.preparation.read_text()), args.offset_ticks)
    with args.output.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result.get('execution_timing', {'offset_ticks': 0})))


if __name__ == '__main__':
    main()
