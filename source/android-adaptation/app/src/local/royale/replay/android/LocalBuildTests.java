package local.royale.replay.android;
import android.app.Instrumentation;
import android.os.Bundle;
import java.io.*;
import org.json.JSONObject;

public final class LocalBuildTests extends Instrumentation {
    @Override public void onCreate(Bundle args){super.onCreate(args);start();}
    @Override public void onStart(){Bundle result=new Bundle();try{
        byte[] raw=MainActivity.read(new FileInputStream(new File(getTargetContext().getFilesDir(),"source.html")),ReplaySource.MAX_BYTES);
        JSONObject report=NativePython.buildSource(getTargetContext(),raw);
        if(report.optLong("export_count",0)!=7||report.optLong("code_pin_count",0)<40||report.optBoolean("game_memory_written",true))throw new AssertionError("phone component build contract differs");
        result.putString("summary",report.toString());finish(-1,result);
    }catch(Throwable error){result.putString("error",error.toString());finish(0,result);}}
}
