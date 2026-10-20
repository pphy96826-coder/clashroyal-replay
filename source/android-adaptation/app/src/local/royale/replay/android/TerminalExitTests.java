package local.royale.replay.android;

import android.app.Instrumentation;
import android.os.Bundle;
import org.json.JSONObject;

/** Explicit terminal-only cleanup integration test. Never starts a game/battle. */
public final class TerminalExitTests extends Instrumentation {
    @Override public void onCreate(Bundle args){super.onCreate(args);start();}
    @Override public void onStart(){Bundle report=new Bundle();try{
        JSONObject state=PlaybackStatus.read(getTargetContext());
        if(!state.optString("state","").equals("complete"))throw new AssertionError("not a completed replay; no operation made");
        NativePython.finishCompleted(getTargetContext(),state);
        JSONObject after=PlaybackStatus.read(getTargetContext());
        if(!after.optString("state","").equals("idle")||PlaybackStatus.ownsTask(after))throw new AssertionError("terminal cleanup did not restore idle");
        report.putString("summary","PASS verified terminal -> owned client process closed -> console idle; no new game or replay started");finish(-1,report);
    }catch(Throwable error){report.putString("error",error.toString());finish(0,report);}}
}
