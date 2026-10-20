package local.royale.replay.android;

import android.app.Instrumentation;
import android.os.Bundle;
import android.content.Context;
import java.io.File;
import org.json.JSONObject;

/** Reconcile the REAL retained job only if its original process is already gone.
 * Never starts/stops a game, creates fake receipts or replaces an active job.
 */
public final class LifecycleIntegrationTests extends Instrumentation {
    @Override public void onCreate(Bundle args){super.onCreate(args);start();}
    @Override public void onStart(){Bundle report=new Bundle();try{
        Context context=getTargetContext();File directory=PlaybackStatus.activeDirectory(context);
        File status=new File(directory,"status.json"),source=new File(directory.getParentFile().getParentFile(),"input.html");
        String beforeStatus=MainActivity.sha(MainActivity.read(new java.io.FileInputStream(status),32768));
        String beforeSource=MainActivity.sha(MainActivity.read(new java.io.FileInputStream(source),ReplaySource.MAX_BYTES));
        JSONObject prior=new JSONObject(MainActivity.text(status,32768));
        if(!NativePython.gameGenerationReleased(prior)){
            report.putString("summary","SKIP real old generation is still alive; no changes made");finish(-1,report);return;
        }
        NativePython.reconcileReleased(context,prior);
        JSONObject state=PlaybackStatus.read(context);
        if(!state.optString("state","").equals("idle")||PlaybackStatus.ownsTask(state)||PlaybackStatus.canStop(state,System.currentTimeMillis()/1000))throw new AssertionError("released old process still owns console");
        if(!beforeStatus.equals(MainActivity.sha(MainActivity.read(new java.io.FileInputStream(status),32768)))||!beforeSource.equals(MainActivity.sha(MainActivity.read(new java.io.FileInputStream(source),ReplaySource.MAX_BYTES))))throw new AssertionError("historical inputs/results were overwritten");
        report.putString("summary","PASS real retained job -> idle after confirmed game process exit; original HTML/status unchanged; no game started or stopped");finish(-1,report);
    }catch(Throwable error){report.putString("error",error.toString());finish(0,report);}}
}
