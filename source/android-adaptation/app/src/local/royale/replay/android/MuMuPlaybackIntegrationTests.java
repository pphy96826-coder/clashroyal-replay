package local.royale.replay.android;

import android.app.Instrumentation;
import android.os.Bundle;
import android.content.Intent;
import java.io.*;
import org.json.JSONObject;

/** Explicit device acceptance: real service, overlay and source-bound handoff. */
public final class MuMuPlaybackIntegrationTests extends Instrumentation {
    private String expected="complete";
    private String lockedSeed="";
    private boolean foregroundPreparation,useQueue,autoImport;
    @Override public void onCreate(Bundle args){super.onCreate(args);if(args!=null){if("released".equals(args.getString("expected")))expected="released";lockedSeed=args.getString("locked_seed","");foregroundPreparation="yes".equals(args.getString("foreground_preparation"));useQueue="yes".equals(args.getString("use_queue"));autoImport="yes".equals(args.getString("auto_import"));}start();}
    @Override public void onStart(){Bundle result=new Bundle();try{
        if(!OverlayAccess.allowed(getTargetContext()))throw new IOException("MuMu test app overlay grant required");
        byte[] raw=MainActivity.read(new FileInputStream(new File(getTargetContext().getFilesDir(),"source.html")),ReplaySource.MAX_BYTES);
        final String hash=MainActivity.sha(raw);
        JSONObject lockedPlan=null;
        if(!lockedSeed.isEmpty()){
            JSONObject prior=new JSONObject(MainActivity.text(new File(getTargetContext().getFilesDir(),"phone-active.json"),8192));
            File checkpoint=PrivateTaskPaths.resolve(getTargetContext().getFilesDir(),new File(prior.getString("directory")),false);
            byte[] proofBytes=MainActivity.read(new FileInputStream(new File(checkpoint,"skill-checkpoint-result.json")),4*1024*1024);
            JSONObject proof=new JSONObject(new String(proofBytes,java.nio.charset.StandardCharsets.UTF_8));
            int seed=Integer.parseInt(lockedSeed);
            if(!hash.equals(proof.optString("source_sha256",""))||proof.getInt("random_seed")!=seed||proof.getJSONArray("solutions").length()!=1)throw new IOException("requested seed lacks a unique qualifying checkpoint");
            lockedPlan=new JSONObject().put("schema","royale-replay.seed-locked-playback.v1").put("source_sha256",hash).put("random_seed",seed)
                .put("checkpoint_directory",checkpoint.getAbsolutePath()).put("checkpoint_result_sha256",MainActivity.sha(proofBytes))
                .put("selected_attempt",proof.getJSONArray("solutions").getJSONObject(0).getJSONObject("evidence").getString("attempt"));
        }
        final File serviceState=new File(getTargetContext().getFilesDir(),"phone-service-state.json");
        final String previousService=serviceState.isFile()?MainActivity.text(serviceState,32768):"";
        getTargetContext().startActivity(new Intent(getTargetContext(),MainActivity.class).addFlags(0x10000000));
        Thread.sleep(500);
        if(autoImport){
            if(PlaybackService.isBusy())throw new IOException("active task must finish before import acceptance");
            ConsoleActions.speedIndex=4; // 4x solely for this explicit device acceptance.
            String row=ReplayQueue.add(getTargetContext().getFilesDir(),raw,MainActivity.checkedSource(raw));
            ReplayQueue.moveTo(getTargetContext().getFilesDir(),row,0);
            ConsoleActions.imported(getTargetContext());
            FloatingConsole.note(getTargetContext(),"导入自动准备验收：就绪后可在游戏悬浮窗点播放。");
            PlaybackService.openGame(getTargetContext());
        }else if(useQueue){
            byte[] queued=ReplayQueue.next(getTargetContext().getFilesDir());
            if(!hash.equals(MainActivity.sha(queued)))throw new IOException("first queued replay differs from acceptance source");
            ConsoleActions.playNext(getTargetContext());
        }else if(lockedPlan!=null)PlaybackService.begin(getTargetContext(),raw,4,true,"","",lockedPlan);
        else PlaybackService.begin(getTargetContext(),raw,4);
        String requestId=null;
        if(foregroundPreparation){
            // First-install extraction can take longer than a fixed 1.5s. Wait
            // for this new service job rather than crashing its UI thread and
            // interrupting the very runtime installation under acceptance.
            boolean prepared=false;long setupDeadline=android.os.SystemClock.elapsedRealtime()+180000;
            while(android.os.SystemClock.elapsedRealtime()<setupDeadline){
                Thread.sleep(250);
                if(!serviceState.isFile())continue;
                String text=MainActivity.text(serviceState,32768);if(text.equals(previousService))continue;
                JSONObject current=new JSONObject(text);
                if(current.optString("state","").equals("request_failed"))throw new IOException(current.toString());
                if(current.has("directory")&&hash.equals(current.optString("source_sha256",""))){prepared=true;break;}
            }
            if(!prepared)throw new IOException("new service job not ready; no foreground handoff attempted");
            final Exception[] openingError=new Exception[1];
            runOnMainSync(new Runnable(){public void run(){try{
                PlaybackService.coverBeforeGame("MuMu 适配测试 · 正在准备","在游戏前台校验本地回放；尚未提交播放。");
                PlaybackService.openGame(getTargetContext());
            }catch(Exception error){openingError[0]=error;}}});
            if(openingError[0]!=null)throw openingError[0];
        }
        long deadline=android.os.SystemClock.elapsedRealtime()+3600000;
        while(android.os.SystemClock.elapsedRealtime()<deadline){
            Thread.sleep(1000);
            String serviceText=MainActivity.text(serviceState,32768);
            JSONObject job=new JSONObject(serviceText);
            if(job.optString("state","").equals("request_failed")&&!serviceText.equals(previousService))throw new IOException(job.toString());
            if(requestId!=null&&!requestId.equals(job.optString("request_id","")))throw new IOException("acceptance job was replaced after binding");
            if(!job.has("directory"))continue;
            File task=PrivateTaskPaths.resolve(getTargetContext().getFilesDir(),new File(job.getString("directory")),false);
            File status=new File(task,"status.json");if(!status.isFile())continue;
            JSONObject state=new JSONObject(MainActivity.text(status,32768));
            if(!hash.equals(state.optString("source_sha256","")))continue;
            String phase=state.optString("state","");
            if(!lockedSeed.isEmpty()&&state.has("random_seed")&&state.getInt("random_seed")!=Integer.parseInt(lockedSeed))throw new IOException("playback changed the selected seed");
            if(requestId==null){
                if(!state.optBoolean("monitor_active",false)){
                    if(serviceText.equals(previousService))continue;
                    if(phase.equals("failed_before_native")||phase.equals("needs_review")||phase.equals("request_failed"))throw new IOException(state.toString());
                    continue;
                }
                requestId=job.getString("request_id");
            }
            if(expected.equals(phase)&&!state.optBoolean("monitor_active",true)){
                if("complete".equals(expected)&&(!state.optBoolean("source_execution_verified",false)||!state.optBoolean("native_roundtrip_verified",false)||!state.optBoolean("client_reopened",false)))throw new AssertionError("completion lacks native execution and client return proof");
                if("released".equals(expected)&&!state.optBoolean("generation_released",false))throw new AssertionError("process release unverified");
                if("complete".equals(expected)){
                    File returned=new File(getTargetContext().getFilesDir(),"phone-requests/"+requestId+"-returned.json");
                    if(!returned.isFile())continue;
                    JSONObject handoff=new JSONObject(MainActivity.text(returned,8192));
                    if(!requestId.equals(handoff.optString("request_id",""))||!handoff.optBoolean("terminal_verified",false)||!hash.equals(handoff.optString("source_sha256","")))throw new IOException("console return does not match this completed replay");
                }
                result.putString("summary",state.toString());finish(-1,result);return;
            }
            if((phase.equals("released")&&!expected.equals("released"))||phase.equals("needs_review")||phase.equals("failed_before_native")||phase.equals("failed_recovered")||phase.equals("request_failed")||phase.equals("cancelled")||phase.equals("scene_left"))throw new IOException(state.toString());
        }
        throw new IOException("device acceptance timed out; original task retained, no retry");
    }catch(Throwable error){result.putString("error",error.toString());finish(0,result);}}
}
