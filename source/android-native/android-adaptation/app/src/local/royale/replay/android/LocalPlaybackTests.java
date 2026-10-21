package local.royale.replay.android;
import android.app.Instrumentation;
import android.os.Bundle;
import java.io.*;
import org.json.JSONObject;

/** Starts only our fixed phone pipeline; result is QUEUED, never playback proof. */
public final class LocalPlaybackTests extends Instrumentation {
    @Override public void onCreate(Bundle args){super.onCreate(args);start();}
    @Override public void onStart(){Bundle result=new Bundle();try{
        byte[] raw=MainActivity.read(new FileInputStream(new File(getTargetContext().getFilesDir(),"source.html")),ReplaySource.MAX_BYTES);
        JSONObject job=NativePython.startPlayback(getTargetContext(),raw,4);
        result.putString("queued_phone_job",job.toString());finish(-1,result);
    }catch(Throwable error){result.putString("error",error.toString());finish(0,result);}}
}
