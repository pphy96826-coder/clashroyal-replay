package local.royale.replay.android;
import android.app.Instrumentation;
import android.os.Bundle;
public final class LocalRecoveryTests extends Instrumentation {
    @Override public void onCreate(Bundle args){super.onCreate(args);start();}
    @Override public void onStart(){Bundle result=new Bundle();try{
        result.putString("summary",NativePython.recoverInitialization(getTargetContext()).toString());finish(-1,result);
    }catch(Throwable error){result.putString("error",error.toString());finish(0,result);}}
}
