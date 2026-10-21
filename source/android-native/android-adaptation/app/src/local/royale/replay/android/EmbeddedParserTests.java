package local.royale.replay.android;
import android.app.Instrumentation;
import android.os.Bundle;
import java.io.*;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;

public final class EmbeddedParserTests extends Instrumentation {
    @Override public void onCreate(Bundle args){super.onCreate(args);start();}
    @Override public void onStart(){Bundle result=new Bundle();try{
        byte[] raw=MainActivity.read(new FileInputStream(new File(getTargetContext().getFilesDir(),"source.html")),ReplaySource.MAX_BYTES);
        ReplaySource.Info precheck=ReplaySource.parse(new String(raw,StandardCharsets.UTF_8));
        JSONObject report=NativePython.importSource(getTargetContext(),raw);
        if(report.optLong("retained_events",0)!=precheck.count()||report.optLong("dropped_actions",-1)!=0||report.optBoolean("native_calls",true))throw new AssertionError("phone import contract mismatch");
        result.putString("summary",report.toString());finish(-1,result);
    }catch(Throwable error){result.putString("error",error.toString());finish(0,result);}}
}
