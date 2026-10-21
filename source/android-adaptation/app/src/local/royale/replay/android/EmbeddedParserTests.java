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
        long began=android.os.SystemClock.elapsedRealtime();
        JSONObject prepared=SourcePreparation.prepare(getTargetContext(),raw);
        long parsedAt=android.os.SystemClock.elapsedRealtime();
        JSONObject report=NativePython.importSource(getTargetContext(),raw);
        if(report.optLong("retained_events",0)!=precheck.count()||report.optLong("dropped_actions",-1)!=0||report.optBoolean("native_calls",true))throw new AssertionError("phone import contract mismatch");
        JSONObject second=NativePython.importSource(getTargetContext(),raw);
        if(prepared.getString("private_source_manifest").equals(report.getString("private_source_manifest"))||report.getString("private_source_manifest").equals(second.getString("private_source_manifest")))throw new AssertionError("playback reused a previous immutable job");
        JSONObject damaged=new JSONObject(prepared.toString()).put("manifest_sha256",new String(new char[64]).replace('\0','0'));
        try{SourcePreparation.checked(getTargetContext().getFilesDir(),damaged,raw);throw new AssertionError("changed manifest accepted");}catch(IOException expected){}
        damaged=new JSONObject(prepared.toString()).put("source_sha256",new String(new char[64]).replace('\0','0'));
        try{SourcePreparation.checked(getTargetContext().getFilesDir(),damaged,raw);throw new AssertionError("foreign source accepted");}catch(IOException expected){}
        report.put("initial_parse_ms",parsedAt-began).put("cached_fresh_jobs_ms",android.os.SystemClock.elapsedRealtime()-parsedAt).put("fresh_jobs_distinct",true).put("cache_corruption_rejected",true);
        result.putString("summary",report.toString());finish(-1,result);
    }catch(Throwable error){result.putString("error",error.toString());finish(0,result);}}
}
