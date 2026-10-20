package local.royale.replay.android;

import android.app.Activity;
import android.content.Context;
import java.io.*;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;

/** One visible-Activity handoff for this exact newly started job, never a cache. */
final class PlaybackHandoff {
    private final Activity activity;
    private boolean visible,checking;
    PlaybackHandoff(Activity activity){this.activity=activity;}
    void resume(){visible=true;}
    void pause(){visible=false;}
    private static boolean inputVerified(JSONObject state){
        return (state.optBoolean("source_execution_verified",false)&&state.optBoolean("native_roundtrip_verified",false))
            ||(state.optBoolean("diagnostic_only",false)&&state.optBoolean("diagnostic_prefix_verified",false)&&!state.optBoolean("complete_replay_verified",true));
    }
    static boolean readyForForeground(JSONObject state,String expectedHash,long now){
        long age=now-state.optLong("updated_at",0);
        return state.optString("state","").equals("ready_to_open")&&expectedHash.matches("[a-f0-9]{64}")
            &&expectedHash.equals(state.optString("source_sha256",""))&&age>=0&&age<=10
            &&inputVerified(state)
            &&state.optLong("retained_events",0)>0&&state.optLong("game_pid",0)>0&&!state.optString("game_start_time","").isEmpty();
    }
    static boolean verified(JSONObject state,String expectedHash,long now){
        long age=now-state.optLong("updated_at",0);
        return state.optString("state","").equals("playing")&&expectedHash.matches("[a-f0-9]{64}")
            &&expectedHash.equals(state.optString("source_sha256",""))&&age>=0&&age<=10
            &&state.optBoolean("standalone_playback_ready",false)&&inputVerified(state)
            &&state.optBoolean("playback_started",false)&&state.optLong("scene_frames",0)>0
            &&state.optLong("tick",0)>state.optLong("scene_initial_tick",Long.MAX_VALUE)
            &&state.optLong("game_pid",0)>0&&!state.optString("game_start_time","").isEmpty();
    }
    private JSONObject request()throws Exception{
        JSONObject value=new JSONObject(MainActivity.text(new File(activity.getFilesDir(),"phone-service-state.json"),32768));
        if(!value.optString("request_id","").matches("[a-f0-9-]{36}")||!value.optString("directory","").equals(PlaybackStatus.activeDirectory(activity).getAbsolutePath()))throw new IOException("not this request");
        return value;
    }
    private File marker(JSONObject request)throws Exception{
        File records=new File(activity.getFilesDir(),"phone-handoffs");
        if(!records.isDirectory()&&!records.mkdir())throw new IOException("无法保存切换记录");
        return new File(records,request.getString("request_id")+"-foreground.json");
    }
    static void recordStarted(Context context,String id,JSONObject state)throws Exception{
        if(!id.matches("[a-f0-9-]{36}"))throw new IOException("invalid request identity");
        File records=new File(context.getFilesDir(),"phone-handoffs");if(!records.isDirectory()&&!records.mkdir())throw new IOException("cannot reserve handoff record");
        File record=new File(records,id+".json");
        if(!record.exists())MainActivity.write(record,new JSONObject().put("request_id",id).put("source_sha256",state.getString("source_sha256")).put("verified_tick",state.optLong("tick",0)).put("created_at",System.currentTimeMillis()/1000).put("overlay_removed_after_actual_start",true).toString().getBytes(StandardCharsets.UTF_8));
    }
    private void openCovered(JSONObject requested,JSONObject current,File record)throws Exception{
        if(!OverlayAccess.ensure(activity))return;
        PlaybackService.coverBeforeGame(current.optBoolean("diagnostic_only",false)?"未完成诊断预览 · 正在打开":"整局校验通过 · 正在打开战场","正在让原生客户端前台加载；确认实际开始后自动收起。");
        JSONObject signal=new JSONObject().put("request_id",requested.getString("request_id")).put("source_sha256",requested.getString("source_sha256")).put("user_requested_game_foreground",true).put("overlay_attached",true).put("created_at",System.currentTimeMillis()/1000);
        MainActivity.write(record,signal.toString().getBytes(StandardCharsets.UTF_8));
        MainActivity.write(new File(PlaybackStatus.activeDirectory(activity),"foreground-request.json"),signal.toString().getBytes(StandardCharsets.UTF_8));
        PlaybackService.openGame(activity);
    }
    static void serviceForeground(Context context,String id,String hash,File directory)throws Exception{
        JSONObject request=new JSONObject(MainActivity.text(new File(context.getFilesDir(),"phone-service-state.json"),32768));
        if(!id.equals(request.optString("request_id",""))||!hash.equals(request.optString("source_sha256",""))
           ||!directory.getAbsolutePath().equals(request.optString("directory",""))||!directory.equals(PlaybackStatus.activeDirectory(context)))return;
        File records=new File(context.getFilesDir(),"phone-handoffs");if(!records.isDirectory()&&!records.mkdir())throw new IOException("cannot reserve handoff");
        File marker=new File(records,id+"-foreground.json");if(marker.exists())return;
        JSONObject current=new JSONObject(MainActivity.text(new File(directory,"status.json"),32768));
        if(!readyForForeground(current,hash,System.currentTimeMillis()/1000)||!OverlayAccess.allowed(context))return;
        PlaybackService.coverBeforeGame(current.optBoolean("diagnostic_only",false)?"未完成诊断预览 · 正在打开":"整局校验通过 · 正在重放","正在加载本场战场，确认实际步进后收起。");
        JSONObject signal=new JSONObject().put("request_id",id).put("source_sha256",hash).put("user_requested_game_foreground",true).put("overlay_attached",true).put("created_at",System.currentTimeMillis()/1000);
        MainActivity.write(marker,signal.toString().getBytes(StandardCharsets.UTF_8));
        MainActivity.write(new File(directory,"foreground-request.json"),signal.toString().getBytes(StandardCharsets.UTF_8));
        PlaybackService.openGame(context);
    }
    void check(){
        if(!visible||checking||!PlaybackService.isBusy())return;
        if(PlaybackService.armedTask())return; // Rows prepared ahead open only on the user's play request (service-driven).
        try{
            final JSONObject requested=request();final File record=marker(requested);
            final JSONObject state=new JSONObject(MainActivity.text(new File(PlaybackStatus.activeDirectory(activity),"status.json"),32768));
            if(record.exists()||!readyForForeground(state,requested.getString("source_sha256"),System.currentTimeMillis()/1000))return;
            checking=true;
            new Thread(new Runnable(){public void run(){boolean generation=false;try{generation=NativePython.sameGameGeneration(state);}catch(Exception ignored){}
                final boolean matched=generation;
                activity.runOnUiThread(new Runnable(){public void run(){try{
                    if(!visible||!matched||record.exists())return;
                    JSONObject latest=request();
                    if(!latest.getString("request_id").equals(requested.getString("request_id")))return;
                    JSONObject current=new JSONObject(MainActivity.text(new File(PlaybackStatus.activeDirectory(activity),"status.json"),32768));
                    if(!readyForForeground(current,requested.getString("source_sha256"),System.currentTimeMillis()/1000))return;
                    openCovered(requested,current,record);
                }catch(Exception error){try{
                    File directory=PlaybackStatus.activeDirectory(activity);
                    MainActivity.write(new File(directory,"stop-request.json"),new JSONObject().put("cancel_before_scene",true).put("reason","overlay or game opening failed: "+error.toString()).toString().getBytes(StandardCharsets.UTF_8));
                }catch(Exception ignored){} }finally{checking=false;}}});
            }}).start();
        }catch(Exception ignored){}
    }
}
