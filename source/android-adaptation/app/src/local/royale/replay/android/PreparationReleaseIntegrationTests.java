package local.royale.replay.android;

import android.app.Instrumentation;
import android.os.Bundle;
import android.content.Context;
import java.io.*;
import org.json.JSONObject;

/** Explicit real-task migration test. Does not attach/start/stop the game. */
public final class PreparationReleaseIntegrationTests extends Instrumentation {
    @Override public void onCreate(Bundle args){super.onCreate(args);start();}
    @Override public void onStart(){Bundle report=new Bundle();try{
        Context context=getTargetContext();File directory=PlaybackStatus.activeDirectory(context);
        File status=new File(directory,"status.json");
        String before=MainActivity.sha(MainActivity.read(new FileInputStream(status),32768));
        JSONObject raw=new JSONObject(MainActivity.text(status,32768));
        JSONObject generation=NativePython.currentGameGeneration();
        if(!NativePython.preparationCandidate(raw)){
            report.putString("summary","SKIP not a pre-native failure; no changes");finish(-1,report);return;
        }
        NativePython.reconcileReleased(context,raw);
        JSONObject state=PlaybackStatus.read(context);
        if(!state.optBoolean("preparation_released",false)||PlaybackStatus.ownsTask(state))throw new AssertionError("preparation remains blocked");
        if(!before.equals(MainActivity.sha(MainActivity.read(new FileInputStream(status),32768))))throw new AssertionError("original diagnostic status changed");
        if(NativePython.generationChanged(generation,NativePython.currentGameGeneration()))throw new AssertionError("game process changed during migration");
        report.putString("summary","PASS real pre-native failure released; original status unchanged, game PID/start-time unchanged; no native replay published");finish(-1,report);
    }catch(Throwable error){report.putString("error",error.toString());finish(0,report);}}
}
