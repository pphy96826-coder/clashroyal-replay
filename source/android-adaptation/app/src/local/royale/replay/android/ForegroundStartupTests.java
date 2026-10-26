package local.royale.replay.android;

import android.app.ActivityManager;
import android.app.Instrumentation;
import android.app.NotificationManager;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.os.SystemClock;
import android.system.Os;
import java.io.*;
import java.nio.file.Files;
import java.util.UUID;
import java.util.zip.ZipInputStream;
import java.util.zip.ZipEntry;
import org.json.JSONObject;

/** Explicit lifecycle test: blocks only a private FIFO, never starts native work or the game. */
public final class ForegroundStartupTests extends Instrumentation {
    private Context context;
    private boolean present(boolean needForeground){
        ActivityManager am=(ActivityManager)context.getSystemService(Context.ACTIVITY_SERVICE);
        for(ActivityManager.RunningServiceInfo info:am.getRunningServices(100))
            if(info.service.getClassName().equals(PlaybackService.class.getName())&&(!needForeground||info.foreground))return true;
        return false;
    }
    private String journal()throws Exception{
        File f=new File(context.getFilesDir(),"playback-service-startup.jsonl");
        return f.isFile()?new String(Files.readAllBytes(f.toPath()),"UTF-8"):"";
    }
    private void await(String stage)throws Exception{
        long deadline=SystemClock.elapsedRealtime()+10000;
        while(!journal().contains("\"stage\":\""+stage+"\"")){
            if(SystemClock.elapsedRealtime()>deadline)throw new AssertionError("Missing lifecycle stage "+stage);
            Thread.sleep(50);
        }
    }
    private void stopped()throws Exception{
        long deadline=SystemClock.elapsedRealtime()+10000;
        while(present(false)||PlaybackService.isBusy()){
            if(SystemClock.elapsedRealtime()>deadline)throw new AssertionError("Test service did not stop");
            Thread.sleep(50);
        }
    }
    @Override public void onCreate(Bundle args){super.onCreate(args);start();}
    @Override public void onStart(){
        Bundle result=new Bundle();File pipe=null;boolean backupReady=false;
        String[] names={"phone-service-state.json","queue-auto-prepare.json","playback-service-startup.jsonl","playback-service-startup.previous.jsonl"};
        byte[][] before=new byte[names.length][];int checks=0;
        try{
            context=getTargetContext();File files=context.getFilesDir();
            if(present(false)||PlaybackService.isBusy()||ReplayReset.blocked(context))throw new AssertionError("An existing service/reset is active; no test changes made");
            File active=new File(files,"phone-active.json");byte[] activeBefore=active.isFile()?Files.readAllBytes(active.toPath()):null;
            for(int i=0;i<names.length;i++){File f=new File(files,names[i]);before[i]=f.isFile()?Files.readAllBytes(f.toPath()):null;}
            backupReady=true;ConsoleActions.setAutomatic(context,false);
            for(int i=2;i<names.length;i++)Files.deleteIfExists(new File(files,names[i]).toPath());
            File requests=new File(files,"phone-requests");requests.mkdirs();
            String id=UUID.randomUUID().toString();pipe=new File(requests,id+".html");Os.mkfifo(pipe.getPath(),0600);
            Intent request=new Intent(context,PlaybackService.class).putExtra("request_id",id).putExtra("speed",1.0);
            context.startForegroundService(request);await("worker_read_source");
            if(!present(true))throw new AssertionError("Cold start is not foreground before blocking input");checks++;
            if(journal().indexOf("on_create_foreground")>journal().indexOf("worker_read_source"))throw new AssertionError("Worker preceded foreground promotion");checks++;
            context.startForegroundService(request);await("duplicate_start_ignored");
            Thread.sleep(7500); // Longer than the issue's 5-second watchdog.
            if(!present(true)||!PlaybackService.isBusy())throw new AssertionError("Slow preparation lost foreground service");checks++;
            if(journal().contains("worker_runtime_start"))throw new AssertionError("Native runtime entered before source validation");checks++;
            if(journal().split("\"stage\":\"worker_read_source\"",-1).length!=2)throw new AssertionError("Duplicate start launched another worker");checks++;
            final long[] beat={0};long posted=SystemClock.elapsedRealtime();runOnMainSync(new Runnable(){public void run(){beat[0]=SystemClock.elapsedRealtime();}});
            if(beat[0]-posted>2000)throw new AssertionError("Main thread blocked by slow input");checks++;
            NotificationManager nm=(NotificationManager)context.getSystemService(Context.NOTIFICATION_SERVICE);
            boolean notified=false;for(android.service.notification.StatusBarNotification n:nm.getActiveNotifications())if(n.getId()==21)notified=true;
            if(!notified)throw new AssertionError("No visible startup notification");checks++;
            // Empty input exits at pure validation, before any game/native step.
            final File fifo=pipe;Thread writer=new Thread(new Runnable(){public void run(){try{new FileOutputStream(fifo).close();}catch(IOException ignored){}}});writer.start();writer.join(10000);
            stopped();await("worker_failed");
            File reset=new File(files,"reset-in-progress.json");
            try{
                Files.write(reset.toPath(),"{}".getBytes("UTF-8"));context.startForegroundService(new Intent(context,PlaybackService.class));
                await("reset_blocked");stopped();Thread.sleep(7500);
                if(PlaybackService.isBusy())throw new AssertionError("Reset-blocked request left busy set");checks++;
            }finally{Files.deleteIfExists(reset.toPath());}
            ByteArrayOutputStream bytes=new ByteArrayOutputStream();DiagnosticExport.write(files,null,bytes,"Startup lifecycle test");boolean exported=false;
            try(ZipInputStream zip=new ZipInputStream(new ByteArrayInputStream(bytes.toByteArray()))){ZipEntry e;while((e=zip.getNextEntry())!=null)if(e.getName().equals("console/playback-service-startup.jsonl"))exported=true;}
            if(!exported)throw new AssertionError("Pre-task startup evidence missing from diagnostic export");checks++;
            if(activeBefore!=null&&!java.util.Arrays.equals(activeBefore,Files.readAllBytes(active.toPath())))throw new AssertionError("Historical active task changed");checks++;
            String evidence=journal();result.putString("startup_journal",evidence);
            for(String line:evidence.split("\n"))if(!line.isEmpty()){
                JSONObject row=new JSONObject(line);if(row.optString("stage").equals("on_create_foreground"))result.putLong("foreground_ms",row.getLong("duration_ms"));
            }
            result.putString("summary","PASS "+checks+" foreground lifecycle checks: cold start, duplicate, 7.5s blocked worker, responsive main, reset rejection and no-task diagnostic; no native/game work");
        }catch(Throwable error){result.putString("error",error.toString());}
        finally{
            if(context!=null&&backupReady)try{
                if(pipe!=null&&PlaybackService.isBusy()){
                    final File fifo=pipe;new Thread(new Runnable(){public void run(){try{new FileOutputStream(fifo).close();}catch(Exception ignored){}}}).start();
                }
                stopped();Thread.sleep(2000); // Let the automatic-queue check run while disabled.
                for(int i=0;i<names.length;i++){File f=new File(context.getFilesDir(),names[i]);if(before[i]==null)Files.deleteIfExists(f.toPath());else Files.write(f.toPath(),before[i]);}
                if(pipe!=null)Files.deleteIfExists(pipe.toPath());
            }catch(Throwable error){result.putString("cleanup_error",error.toString());}
            finish(result.containsKey("error")||result.containsKey("cleanup_error")?0:-1,result);
        }
    }
}
