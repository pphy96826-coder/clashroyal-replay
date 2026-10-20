package local.royale.replay.android;
import android.app.Instrumentation;
import android.os.Bundle;
import java.io.*;
import org.json.JSONObject;

public final class LocalPreparationTests extends Instrumentation {
    @Override public void onCreate(Bundle args){super.onCreate(args);start();}
    @Override public void onStart(){Bundle result=new Bundle();try{
        byte[] raw=MainActivity.read(new FileInputStream(new File(getTargetContext().getFilesDir(),"source.html")),ReplaySource.MAX_BYTES);
        JSONObject report=NativePython.prepareSource(getTargetContext(),raw);
        if(report.optLong("native_tower_types",0)!=4||report.optLong("native_card_count",0)<8
            ||report.optBoolean("standalone_playback_ready",true)||report.optBoolean("game_memory_written",true))throw new AssertionError("local native preparation contract mismatch");
        result.putString("summary",report.toString());finish(-1,result);
    }catch(Throwable error){result.putString("error",error.toString());finish(0,result);}}
}
