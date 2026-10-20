"""Explicit, uncached timing A/B input; never change the downloaded source.

The legacy source_tick_20hz field is the execution target consumed by the
existing probe. Preserve the original HTML data_t and a per-event original
tick, so an experiment cannot be mistaken for a lossless source reconstruction.
No default importer, terminal rule, native engine or production cache is changed.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from bootstrap_input import validate


def shift(preparation, offset_ticks):
    validate(preparation)
    if type(offset_ticks) is not int or not -200 <= offset_ticks <= 200 or not offset_ticks:
        raise ValueError('explicit nonzero offset within ten seconds required')
    if 'timing_experiment' in preparation:
        raise ValueError('do not compound timing experiments')
    result = copy.deepcopy(preparation)
    for event in result['events']:
        original = event['source_tick_20hz']
        if event['source_fields']['data_t'] != original:
            raise ValueError('original HTML tick does not match baseline')
        if original + offset_ticks < 0:
            raise ValueError('negative execution tick; never clamp or drop events')
        event['original_source_tick_20hz'] = original
        event['source_tick_20hz'] = original + offset_ticks
    result['timing_experiment'] = {
        'test_only': True, 'register_in_production_cache': False,
        'offset_ticks': offset_ticks, 'offset_seconds': offset_ticks / 20,
        'all_deployments_and_abilities_shifted': True,
        'html_source_fields_unchanged': True,
        'initialization_and_terminal_rules_unchanged': True,
    }
    validate(result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preparation', type=Path, required=True)
    parser.add_argument('--offset-ticks', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.preparation.read_bytes()
    result = shift(json.loads(raw), args.offset_ticks)
    result['timing_experiment'].update(
        baseline_preparation=str(args.preparation.resolve()),
        baseline_preparation_sha256=hashlib.sha256(raw).hexdigest())
    with args.output.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result['timing_experiment']))


if __name__ == '__main__':
    main()
