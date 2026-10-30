from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
JAVA=ROOT/'app/src/local/royale/replay/android'

def test_web_entry_checks_source_and_does_not_overwrite_or_retry_existing_tasks():
    source=(JAVA/'WebWorkerActivity.java').read_text()
    assert 'ledger.createNewFile()' in source
    assert source.index('ledger.createNewFile()')<source.index('PlaybackService.begin(')
    assert 'MainActivity.sha(source).equals(sha)' in source
    assert 'tag.equals(info.tag)' in source
    assert 'PlaybackStatus.ownsTask(PlaybackStatus.read(WebWorkerActivity.this))' in source
    assert 'web-inbox/' in source and '/data/local/tmp/' not in source
    for forbidden in ('Runtime.getRuntime','force-stop','http://','https://'):
        assert forbidden not in source

def test_web_playback_waits_for_its_own_started_audio_recording():
    source=(JAVA/'PlaybackService.java').read_text()
    assert 'webRecordingReady(status.getParentFile(),webJobId,MainActivity.sha(source))' in source
    body=source[source.index('static boolean webRecordingReady('):source.index('static void openGame(')]
    assert 'if(webJobId.isEmpty())return true' in body
    assert 'value.optBoolean("recording_started",false)' in body
    assert 'value.optBoolean("system_audio",false)' in body
    assert 'webJobId.equals(value.optString("job_id",""))' in body
    assert 'sourceHash.equals(value.optString("source_sha256",""))' in body

def test_web_task_directory_is_persisted_separately_from_global_status():
    entry=(JAVA/'WebWorkerActivity.java').read_text()
    body=entry[entry.index('static void bindTask('):entry.index('@Override public void onCreate')]
    assert 'PrivateTaskPaths.resolve' in body
    assert 'receipt.exists()' in body
    for name in ('job_id','request_id','source_sha256','directory'):
        assert '.put("'+name+'"' in body
    service=(JAVA/'PlaybackService.java').read_text()
    assert service.index('NativePython.startPlayback(')<service.index('WebWorkerActivity.bindTask(')
    assert 'if(id.isEmpty())return;' in body
