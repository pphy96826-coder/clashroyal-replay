package local.royale.replay.android;
import android.app.Instrumentation;
import android.os.Bundle;
import org.json.JSONObject;

/** Device platform tests, no WebView, network, root or game invocation. */
public final class ConsoleTests extends Instrumentation {
    @Override public void onCreate(Bundle args){super.onCreate(args);start();}
    @Override public void onStart(){Bundle report=new Bundle();int count=0;try{
        if(BrowserPolicy.allowed("http://royaleapi.com/")||BrowserPolicy.allowed("https://royaleapi.com.evil.test/")||BrowserPolicy.allowed("file:///data/x")||BrowserPolicy.allowed("https://royaleapi.com@evil.test/"))throw new AssertionError("unsafe URL accepted");count++;
        if(!BrowserPolicy.replayTag("https://royaleapi.com/replay?tag=09C9CLU28L9V&x=1").equals("09C9CLU28L9V")||!BrowserPolicy.replayTag("https://royaleapi.com/replay?tag=ABCDEF&tag=ZZZZZZ").isEmpty())throw new AssertionError("tag identity mismatch");count++;
        JSONObject live=new JSONObject().put("state","playing").put("tick",2400).put("native_terminal_tick",6208).put("game_pid",1).put("updated_at",1000).put("monitor_active",true);
        if(!PlaybackStatus.title(live).equals("正在播放 · 2:00 / 5:10")||!PlaybackStatus.canStop(live,1001))throw new AssertionError("live status incorrect");count++;
        if(PlaybackStatus.canStop(live,1040)||!PlaybackStatus.detail(live,1040).contains("状态已过期"))throw new AssertionError("stale status accepted");count++;
        live.put("state","needs_review");if(PlaybackStatus.canStop(live,1001))throw new AssertionError("failed task offered a dead stop");count++;
        live.put("state","complete").put("monitor_active",false);if(PlaybackStatus.canStop(live,1001)||!PlaybackStatus.detail(live,1001).contains("实时观察已结束"))throw new AssertionError("expired monitor accepted");count++;
        JSONObject proof=new JSONObject("{\"errors\":[],\"detached\":true,\"battle_terminal\":true,\"native_replay_scene_present\":true,\"scene_state\":{\"tick\":6208},\"local_driver\":{\"error\":0,\"terminal_tick\":6208}}");
        if(!PlaybackStatus.terminalVerified(proof)||PlaybackStatus.terminalVerified(new JSONObject()))throw new AssertionError("terminal proof gate incorrect");count++;
        proof.getJSONObject("local_driver").put("error",1);if(PlaybackStatus.terminalVerified(proof))throw new AssertionError("failed driver accepted as terminal proof");count++;
        android.app.Notification notification=PlaybackService.progressNotification(getTargetContext(),"测试进度","不发通知、不启动游戏",true);
        if(notification.contentIntent==null||!notification.contentIntent.getCreatorPackage().equals("local.royale.replay.android"))throw new AssertionError("notification has no console return target");count++;
        String hash="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        JSONObject started=new JSONObject().put("state","playing").put("source_sha256",hash).put("updated_at",1000).put("standalone_playback_ready",true).put("native_roundtrip_verified",true).put("playback_started",true).put("scene_frames",3).put("scene_initial_tick",10).put("tick",20).put("game_pid",1).put("game_start_time","42");
        if(!PlaybackHandoff.verified(started,hash,1001))throw new AssertionError("fresh verified play refused");count++;
        for(String phase:new String[]{"queued","loading","waiting_lobby","starting","waiting_foreground","needs_review","complete"}){
            started.put("state",phase);if(PlaybackHandoff.verified(started,hash,1001))throw new AssertionError("premature handoff "+phase);count++;
        }
        started.put("state","playing");
        if(PlaybackHandoff.verified(started,hash,1020)||PlaybackHandoff.verified(started,hash.replace('a','b'),1001))throw new AssertionError("stale/foreign source handoff");count++;
        started.put("tick",10);if(PlaybackHandoff.verified(started,hash,1001))throw new AssertionError("no actual step handoff");count++;
        JSONObject generation=new JSONObject().put("game_pid",1).put("game_start_time","42");
        if(NativePython.generationChanged(generation,generation))throw new AssertionError("same process released");count++;
        if(!NativePython.generationChanged(generation,new JSONObject().put("game_pid",1).put("game_start_time","43")))throw new AssertionError("reused PID not detected");count++;
        JSONObject ready=new JSONObject().put("state","ready_to_open").put("source_sha256",hash).put("updated_at",1000).put("source_execution_verified",true).put("native_roundtrip_verified",true).put("retained_events",154).put("game_pid",1).put("game_start_time","42");
        if(!PlaybackHandoff.readyForForeground(ready,hash,1001)||PlaybackHandoff.verified(ready,hash,1001))throw new AssertionError("ready confused with actual playback");count++;
        ready.put("source_execution_verified",false);if(PlaybackHandoff.readyForForeground(ready,hash,1001))throw new AssertionError("incomplete source opened game");count++;
        JSONObject lobby=new JSONObject().put("state","waiting_lobby");
        if(!PlaybackStatus.title(lobby).contains("等待游戏大厅就绪")||!PlaybackStatus.detail(lobby,1001).contains("尚不是播放成功"))throw new AssertionError("lobby wait pretends to play");count++;
        if(!NativePython.releasedStat(generation,0,"REPLAY_PROCESS_ABSENT"))throw new AssertionError("absent process not released");count++;
        try{NativePython.releasedStat(generation,1,"permission denied");throw new AssertionError("permission denial became exit");}catch(java.io.IOException expected){}count++;
        StringBuilder stat=new StringBuilder("1 (game process) S");for(int i=1;i<19;i++)stat.append(" 0");stat.append(" 42");
        if(NativePython.releasedStat(generation,0,stat.toString()))throw new AssertionError("live same generation released");count++;
        if(!NativePython.releasedStat(generation,0,stat.toString().replace(" 42"," 43")))throw new AssertionError("reused PID not released");count++;
        JSONObject release=new JSONObject().put("game_pid",1).put("game_start_time","42").put("generation_released",true);
        if(!PlaybackStatus.releaseMatches(generation,release))throw new AssertionError("valid release ignored");count++;
        release.put("game_start_time","43");if(PlaybackStatus.releaseMatches(generation,release))throw new AssertionError("foreign generation released");count++;
        if(PlaybackStatus.ownsTask(new JSONObject().put("state","released")))throw new AssertionError("released task still owns UI");count++;
        JSONObject pre=new JSONObject().put("state","failed_before_native").put("native_entry_started",false);
        if(!PlaybackStatus.ownsTask(pre)||!NativePython.preparationCandidate(pre))throw new AssertionError("unverified release accepted");count++;
        pre.put("preparation_released",true);
        if(PlaybackStatus.ownsTask(pre))throw new AssertionError("proven pre-native failure blocks replay");count++;
        if(NativePython.preparationCandidate(new JSONObject().put("state","playing")))throw new AssertionError("live scene offered pre-native release");count++;
        java.io.File savedFiles=new java.io.File(getTargetContext().getFilesDir(),"saved-replay-test-"+java.util.UUID.randomUUID());
        if(!savedFiles.mkdir())throw new java.io.IOException("test directory");
        byte[] sample=MainActivity.read(getTargetContext().getAssets().open("synthetic.html"),ReplaySource.MAX_BYTES);
        SavedReplay.save(savedFiles,sample,MainActivity.checkedSource(sample));
        String selectedHash=MainActivity.sha(sample);
        if(!MainActivity.sha(SavedReplay.load(savedFiles,selectedHash)).equals(selectedHash))throw new AssertionError("saved source changed");count++;
        try{SavedReplay.load(savedFiles,hash);throw new AssertionError("wrong source replayed");}catch(java.io.IOException expected){}count++;
        SavedReplay.hide(savedFiles,selectedHash);
        if(SavedReplay.metadata(savedFiles)!=null||!new java.io.File(savedFiles,"source.html").isFile())throw new AssertionError("removal deleted original or remained visible");count++;
        SavedReplay.save(savedFiles,sample,MainActivity.checkedSource(sample));
        if(SavedReplay.metadata(savedFiles)==null)throw new AssertionError("reimport did not restore saved source");count++;
        report.putString("summary","PASS "+count+" console/handoff/status tests; no network or native playback invoked");finish(-1,report);
    }catch(Throwable error){report.putString("error",error.toString());finish(0,report);}}
}
