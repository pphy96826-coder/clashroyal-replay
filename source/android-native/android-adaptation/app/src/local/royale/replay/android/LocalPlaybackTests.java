package local.royale.replay.android;
import android.app.Instrumentation;
import android.os.Bundle;
import java.io.*;
import org.json.JSONObject;

/** Starts only our fixed phone pipeline; result is QUEUED, never playback proof. */
public final class LocalPlaybackTests extends Instrumentation {
    private Bundle options;
    @Override public void onCreate(Bundle args){super.onCreate(args);options=args;start();}
    @Override public void onStart(){Bundle result=new Bundle();try{
        File source=new File(getTargetContext().getFilesDir(),"source.html");
        if(options!=null&&"yes".equals(Bundle.class.getMethod("getString",String.class).invoke(options,"capture_probe"))){
            String name=(String)Bundle.class.getMethod("getString",String.class).invoke(options,"source_file");
            if(!name.matches("web-inbox/[a-f0-9-]{36}\\.html"))throw new IOException("probe source must be an existing private inbox HTML");
            source=new File(getTargetContext().getFilesDir(),name);
            byte[] sample=MainActivity.read(new FileInputStream(source),ReplaySource.MAX_BYTES);
            String id=PlaybackService.begin(getTargetContext(),sample,1,true,"","","");
            result.putString("capture_probe_request",id);
            long until=System.currentTimeMillis()+300000;
            while(PlaybackService.isBusy()&&System.currentTimeMillis()<until)Thread.sleep(250);
            if(PlaybackService.isBusy())throw new IOException("probe did not finish; original state retained");
            finish(-1,result);return;
        }
        byte[] raw=MainActivity.read(new FileInputStream(source),ReplaySource.MAX_BYTES);
        JSONObject job=NativePython.startPlayback(getTargetContext(),raw,4);
        result.putString("queued_phone_job",job.toString());finish(-1,result);
    }catch(Throwable error){result.putString("error",error.toString());finish(0,result);}}
}
