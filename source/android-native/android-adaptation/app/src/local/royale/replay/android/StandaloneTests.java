package local.royale.replay.android;

import android.app.Instrumentation;
import android.os.Bundle;
import java.io.File;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;

/** Explicitly invoked, already-authorized, read-only device doctor. */
public final class StandaloneTests extends Instrumentation {
    @Override public void onCreate(Bundle args){super.onCreate(args);start();}
    @Override public void onStart(){Bundle result=new Bundle();try{
        String apk=getTargetContext().getPackageManager().getApplicationInfo(StandaloneDoctor.GAME,0).sourceDir;
        JSONObject report=StandaloneDoctor.inspect(new File(apk));
        MainActivity.write(new File(getTargetContext().getFilesDir(),"standalone-doctor.json"),report.toString().getBytes(StandardCharsets.UTF_8));
        result.putString("summary",report.toString());
        finish(report.optBoolean("local_debug_prerequisites_passed",false)?-1:0,result);
    }catch(Exception error){result.putString("error",error.toString());finish(0,result);}}
}
