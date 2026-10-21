"""Source/generation-bound early selection; never interrupts a published task."""
import json

class BestRequested(Exception):pass

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
