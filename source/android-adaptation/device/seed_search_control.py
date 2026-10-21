"""Source/generation-bound early selection; never interrupts a published task."""
import json

class BestRequested(Exception):pass

def search_reasons(preparation,source):
    """Only actual Hunter plays or an identifiable Skeleton King ability.

    Deck membership alone is insufficient. Generic ability markers with
    multiple deployed ability-capable cards cannot identify a Skeleton King.
    """
    hunter,skeleton_king=26000044,26000069
    champions={26000065,26000069,26000072,26000074,26000077,26000093,26000099,26000103}
    capable={deck['source_side']:champions|{card['base_data_id'] for card in deck['cards'] if card.get('form')=='hero'} for deck in source['decks']}
    played={};reasons=[]
    for event in sorted(preparation['events'],key=lambda row:row['source_tick_20hz']):
        side=event['source_side'];card=event.get('base_data_id')
        if event['kind']=='play_card':
            if card==hunter and 'hunter_played' not in reasons:reasons.append('hunter_played')
            if card in capable.get(side,champions):played.setdefault(side,set()).add(card)
        elif event['kind']=='activate_ability' and played.get(side)=={skeleton_king}:
            if 'skeleton_king_ability' not in reasons:reasons.append('skeleton_king_ability')
    return reasons


def requested(path,source_sha256,identity):
    try:
        if path.stat().st_size>4096:return False
        value=json.loads(path.read_text())
        if not isinstance(value,dict):return False
        return (value.get('schema')=='royale-replay.accept-best-seed.v1'
            and value.get('play_best') is True and value.get('source_sha256')==source_sha256
            and type(value.get('game_pid')) is int and value['game_pid']==identity['pid']
            and value.get('game_start_time')==identity['process_start_time'])
    except (OSError,ValueError,TypeError):return False

def choose_trials(best,seeds,evaluate,should_stop,progress,cancel_error):
    """best is an already fully executed run; lower rank is better.

    Native work is serial. An in-flight task may finish, then compete before
    stopping. A partial calibration/candidate can never replace the best run.
    """
    attempts=[];stopped=False
    for number,seed in enumerate(seeds):
        if should_stop():stopped=True;break
        progress(number,seed,best)
        row={'seed':seed}
        try:
            trial=evaluate(seed,number)
            if len(trial)!=5 or trial[1]!=seed:raise ValueError('seed trial identity differs')
            row.update(executed=True,tier=trial[2],difference=trial[3])
            if trial[0]<best[0]:best=trial
        except BestRequested:
            row.update(executed=False,stopped_at_safe_boundary=True)
            attempts.append(row);stopped=True;break
        except Exception as error:
            if isinstance(error,cancel_error):raise
            row.update(executed=False,error=str(error)[:300])
        attempts.append(row)
        if best[2]=='exact':break
        if should_stop():stopped=True;break
    return best,attempts,stopped
