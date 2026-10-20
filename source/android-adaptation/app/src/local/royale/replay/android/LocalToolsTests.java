package local.royale.replay.android;
import android.app.Instrumentation;
import android.os.Bundle;
import org.json.JSONObject;

public final class LocalToolsTests extends Instrumentation {
    @Override public void onCreate(Bundle args){super.onCreate(args);start();}
    @Override public void onStart(){Bundle result=new Bundle();try{
        JSONObject report=NativePython.checkTools(getTargetContext());
        result.putString("summary",report.toString());finish(-1,result);
    }catch(Throwable error){result.putString("error",error.toString());finish(0,result);}}
}
