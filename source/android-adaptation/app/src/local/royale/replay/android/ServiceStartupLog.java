package local.royale.replay.android;

import android.content.Context;
import android.os.SystemClock;
import android.util.Log;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.json.JSONObject;

/** Bounded private lifecycle evidence, even before a Python task exists. */
final class ServiceStartupLog {
    private static final ExecutorService writer=Executors.newSingleThreadExecutor();
    static void record(Context context,final String stage,String request,long elapsed){
        final Context app=context.getApplicationContext();
        final String id=request!=null&&request.matches("[a-f0-9-]{36}")?request:"";
        final long now=SystemClock.elapsedRealtime(),duration=elapsed;
        final int pid=android.os.Process.myPid();
        Log.i("ReplayService","stage="+stage+" request="+id+" elapsed_ms="+duration);
        writer.execute(new Runnable(){public void run(){try{
            File file=new File(app.getFilesDir(),"playback-service-startup.jsonl");
            if(file.length()>=65536){
                File prior=new File(app.getFilesDir(),"playback-service-startup.previous.jsonl");
                if(prior.exists()&&!prior.delete())return;
                if(!file.renameTo(prior))return;
            }
            JSONObject value=new JSONObject().put("stage",stage).put("request_id",id).put("pid",pid)
                .put("elapsed_realtime_ms",now).put("duration_ms",duration).put("recorded_at",System.currentTimeMillis()/1000);
            try(FileOutputStream out=new FileOutputStream(file,true)){out.write((value.toString()+"\n").getBytes(StandardCharsets.UTF_8));}
        }catch(Exception error){Log.w("ReplayService","Could not retain startup record",error);}}});
    }
    private ServiceStartupLog(){}
}
