package local.royale.replay.android;

import android.content.Context;
import java.io.*;
import java.util.Locale;
import org.json.JSONObject;

/** Single phone-native status source; legacy desktop statuses cannot overwrite it. */
public final class PlaybackStatus {
    static File activeDirectory(Context context)throws Exception{
        return taskDirectory(context,false);
    }
    static File taskDirectory(Context context,boolean allowMissing)throws Exception{
        JSONObject active=new JSONObject(MainActivity.text(new File(context.getFilesDir(),"phone-active.json"),8192));
        return PrivateTaskPaths.resolve(context.getFilesDir(),new File(active.getString("directory")),allowMissing);
    }
    static boolean launchFailureReleased(Context context)throws Exception{
        JSONObject active=new JSONObject(MainActivity.text(new File(context.getFilesDir(),"phone-active.json"),8192));
        if(!active.optBoolean("launch_failed_before_native_entry",false))return false;
        File directory=taskDirectory(context,true),parent=directory.getParentFile();
        JSONObject request=new JSONObject(MainActivity.text(new File(parent,"play-request.json"),32768));
        JSONObject source=new JSONObject(MainActivity.text(new File(parent,"source.json"),4*1024*1024));
        return PrivateTaskPaths.launchFailureProven(directory,true,active.optString("source_sha256",""),
            request.optString("source_sha256",""),source.optString("source_sha256",""),new File(request.getString("source_manifest")));
    }
    static JSONObject read(Context context)throws Exception{
        JSONObject state=new JSONObject().put("state","idle");
        try{
            File directory=activeDirectory(context);
            state=new JSONObject(MainActivity.text(new File(directory,"status.json"),32768));
            if(preparationReleased(context,directory)){
                JSONObject release=new JSONObject(MainActivity.text(new File(directory,"preparation-release.json"),8192));
                state.put("state","failed_before_native").put("preparation_released",true).put("monitor_active",false)
                    .put("message","上次准备失败，未进入原生执行，已解除错误占用。可重新选择 HTML；原始文件和诊断记录保留。\n"+release.optString("reason",""));
            }
            if(state.optString("state","").equals("needs_review")){
                File terminalFile=new File(directory,"scene-v1-terminal-result.json");
                if(terminalFile.isFile()){
                    JSONObject terminal=new JSONObject(MainActivity.text(terminalFile,128*1024));
                    if(terminalVerified(terminal))state.put("state","complete").put("monitor_active",false)
                        .put("message","原生终局已验证；之后的场景观察异常已保留，不影响这次已完成回放。不会重试或自动关闭游戏。")
                        .put("native_terminal_tick",terminal.getJSONObject("scene_state").optLong("tick",0));
                }
            }
        }catch(FileNotFoundException ignored){}catch(IOException ignored){}
        File serviceFile=new File(context.getFilesDir(),"phone-service-state.json");
        if(serviceFile.isFile()){
            JSONObject service=new JSONObject(MainActivity.text(serviceFile,32768));
            if(service.optLong("updated_at",0)>state.optLong("updated_at",0)){
                if(service.optString("state","").equals("request_failed")&&state.optBoolean("preparation_released",false))state.put("last_request_error","");
                else if(service.optString("state","").equals("request_failed")&&ownsTask(state))state.put("last_request_error",service.optString("message",""));
                else state=service;
            }
        }
        // A release receipt only changes the UI/lease, never historical native
        // results. PID + start time prevents a stale receipt releasing a new job.
        try{
            JSONObject release=new JSONObject(MainActivity.text(new File(activeDirectory(context),"process-release.json"),8192));
            if(releaseMatches(state,release)){
                boolean dismissed=false;
                try{dismissed=terminalChoiceMatches(state,new JSONObject(MainActivity.text(new File(activeDirectory(context),"terminal-choice.json"),8192)));}catch(IOException ignored){}
                boolean keepComplete=!state.optBoolean("monitor_active",true)&&completedVerified(activeDirectory(context),state)&&!dismissed;
                state.put("monitor_active",false).put("generation_released",true).put("terminal_choice_confirmed",dismissed).put("last_request_error","");
                if(!keepComplete)state.put("state","idle").put("updated_at",release.optLong("updated_at",state.optLong("updated_at",0)))
                    .put("message","游戏回放进程已结束，控制台已就绪。原始 HTML 和终局记录已保留，可重新选择回放。");
            }
        }catch(FileNotFoundException ignored){}catch(IOException ignored){}
        if(state.optString("state","").equals("released"))state.put("state","idle");
        try{
            if(launchFailureReleased(context)){
                String reason="";File log=new File(taskDirectory(context,true).getParentFile(),"play-process.log");
                try{String text=MainActivity.text(log,16384).trim();String[] lines=text.split("\\n");reason=lines.length==0?"":lines[lines.length-1];if(reason.length()>240)reason=reason.substring(reason.length()-240);}catch(IOException ignored){}
                state.put("state","failed_before_native").put("preparation_released",true).put("launch_failure_released",true).put("monitor_active",false)
                    .put("message","上次本机执行器已在原生执行前退出，未创建战斗任务；已核验并解除启动失败占用。可重新选择回放，不需要清数据或重启游戏。请导出诊断以检查启动原因。"+(reason.isEmpty()?"":"\n启动信息："+reason));
            }
        }catch(Exception ignored){/* Missing/inaccessible proof is not permission to release. */}
        return state;
    }
    static boolean releaseMatches(JSONObject state,JSONObject release){
        return release.optBoolean("generation_released",false)&&state.optLong("game_pid",0)>0
            &&state.optLong("game_pid",0)==release.optLong("game_pid",-1)
            &&!state.optString("game_start_time","").isEmpty()
            &&state.optString("game_start_time","").equals(release.optString("game_start_time",""));
    }
    static boolean terminalChoiceMatches(JSONObject state,JSONObject choice){
        return choice.optBoolean("terminal_choice_confirmed",false)&&state.optLong("game_pid",0)>0
            &&state.optLong("game_pid",0)==choice.optLong("game_pid",-1)
            &&!state.optString("game_start_time","").isEmpty()&&state.optString("game_start_time","").equals(choice.optString("game_start_time",""))
            &&state.optString("source_sha256","").matches("[a-f0-9]{64}")&&state.optString("source_sha256","").equals(choice.optString("source_sha256",""));
    }
    static boolean preparationReleased(Context context,File directory)throws Exception{
        File proof=new File(directory,"preparation-release.json");if(!proof.isFile())return false;
        JSONObject active=new JSONObject(MainActivity.text(new File(context.getFilesDir(),"phone-active.json"),8192));
        JSONObject release=new JSONObject(MainActivity.text(proof,8192));
        File current=new File(active.optString("directory",""));
        return current.isDirectory()&&java.nio.file.Files.isSameFile(directory.toPath(),current.toPath())&&release.optBoolean("native_not_entered",false)
            &&active.optString("source_sha256","").equals(release.optString("source_sha256","missing"))
            &&MainActivity.sha(MainActivity.read(new FileInputStream(new File(directory,"status.json")),32768)).equals(release.optString("status_sha256",""));
    }
    static boolean completedVerified(File directory,JSONObject state)throws Exception{
        if(!state.optString("state","").equals("complete"))return false;
        File proof=new File(directory,"scene-v1-terminal-result.json");
        return proof.isFile()&&terminalVerified(new JSONObject(MainActivity.text(proof,128*1024)));
    }
    static boolean terminalVerified(JSONObject proof){
        JSONObject scene=proof.optJSONObject("scene_state"),driver=proof.optJSONObject("local_driver");
        return proof.optBoolean("detached",false)&&proof.optBoolean("native_replay_scene_present",false)&&proof.optBoolean("battle_terminal",false)
            &&"[]".equals(proof.optString("errors","missing"))&&scene!=null&&driver!=null&&driver.optLong("error",-1)==0
            &&scene.optLong("tick",0)>0&&scene.optLong("tick",0)==driver.optLong("terminal_tick",-1);
    }
    static boolean ownsTask(JSONObject state){String p=state.optString("state","");if(p.equals("failed_before_native"))return !state.optBoolean("preparation_released",false);return !(p.equals("idle")||p.equals("released")||p.equals("stopped")||p.equals("cancelled")||p.equals("request_failed")||p.equals("failed_recovered"));}
    static boolean canStop(JSONObject state,long now){String p=state.optString("state","");return ownsTask(state)&&!p.equals("needs_review")&&!p.equals("scene_left")&&state.optLong("game_pid",0)>0&&state.optBoolean("monitor_active",true)&&now-state.optLong("updated_at",0)<30;}
    static String title(JSONObject state){
        String p=state.optString("state","idle");
        if(p.equals("queued"))return "准备中 · 正在启动本机任务";
        if(p.equals("preparing"))return "准备中 · 读取回放与资源";
        if(p.equals("calibrating"))return "准备中 · 校准初始手牌";
        if(p.equals("simulating"))return state.optString("message","").contains("随机种子")?"校验中 · 匹配随机种子":"校验中 · 原生引擎执行整局";
        if(p.equals("validating"))return "校验中 · 核对全部指令";
        if(p.equals("loading"))return "加载中 · 等待战场画面";
        if(p.equals("ready_to_open")){String m=ConsoleActions.pageMatch(state);
            return m.equals("exact")?"整局校验通过 · 准备前台加载":m.equals("same_towers")?"终局近似网页 · 准备前台加载":"⚠ 终局与网页不符 · 准备前台加载";}
        if(p.equals("waiting_lobby"))return "加载中 · 等待游戏大厅就绪";
        if(p.equals("starting"))return "确认中 · 等待原生回放实际步进";
        if(p.equals("waiting_foreground"))return "等待游戏画面 · 尚未确认开始";
        if(p.equals("playing")){String m=ConsoleActions.pageMatch(state);
            return (m.equals("exact")?"":m.equals("same_towers")?"终局近似 · ":"⚠ 与网页不符 · ")+"正在播放 · "+clock(state.optLong("tick",0))+" / "+clock(state.optLong("native_terminal_tick",0));}
        if(p.equals("diagnostic_ready"))return "诊断预览已暂停 · 非完整回放";
        if(p.equals("returning_lobby"))return "播放完成 · 正在重新打开游戏";
        if(p.equals("complete"))return "播放完成 · 已到终局";
        if(p.equals("needs_review"))return "任务未完成 · 请查看提示";
        if(p.equals("failed_recovered"))return "回放未完成 · 已恢复，可重新选择";
        if(p.equals("failed_before_native"))return "准备失败 · 可重新选择回放";
        if(p.equals("monitor_expired"))return "观察已结束 · 未重试或关闭游戏";
        if(p.equals("scene_left"))return "已离开回放 · 原记录保留";
        if(p.equals("stopped")||p.equals("cancelled"))return "已停止 · 可重新选择 HTML";
        if(p.equals("request_failed"))return "未开始播放";
        return "就绪 · 选择回放即可播放";
    }
    static String detail(JSONObject state,long now){
        String message=state.optString("message","选择 HTML 后自动准备并播放；不使用电脑后端。");
        long updated=state.optLong("updated_at",0),age=Math.max(0,now-updated);
        String phase=state.optString("state","");
        long phaseStart=state.optLong("phase_started_at",0),started=state.optLong("preparation_started_at",0);
        if(state.optBoolean("monitor_active",false)&&phaseStart>0&&started>0
            &&(phase.equals("preparing")||phase.equals("calibrating")||phase.equals("simulating")||phase.equals("validating")||phase.equals("loading")))
            message+="\n本阶段已用 "+Math.max(0,now-phaseStart)+" 秒 · 本次流程已用 "+Math.max(0,now-started)+" 秒";
        if(updated>0)message+="\n状态更新："+(age<3?"刚刚":age+" 秒前");
        if((phase.equals("playing")&&age>15)||((phase.equals("preparing")||phase.equals("calibrating")||phase.equals("simulating")||phase.equals("validating")||phase.equals("loading"))&&age>120))message+="\n状态已过期，不能据此确认仍在正常运行；不会自动重试。";
        if(phase.equals("complete")&&(!state.optBoolean("monitor_active",true)||age>30))message+="\n这是已完成记录；实时观察已结束。点重放可重新播放本场，点退出回放可安全关闭游戏回放进程。";
        if(phase.equals("complete")&&state.has("page_match")){
            String match=ConsoleActions.pageMatch(state);
            if(match.equals("same_towers"))message+="\n终局近似：被摧毁塔楼一致，存活塔血合计相差 "+state.optLong("page_hp_difference",0)+"。";
            else if(!match.equals("exact"))message+="\n本场终局与网页不完全一致，匹配等级："+match+"。";
            else if(state.optBoolean("random_seed_inferred",false))message+="\n终局塔血一致；随机种子为推断值。";
        }
        if(!state.optString("last_request_error","").isEmpty())message+="\n最近操作："+state.optString("last_request_error","");
        if(phase.equals("queued")||phase.equals("preparing"))message+="\n准备阶段留在控制台；整局核验通过后会显示悬浮进度卡并打开游戏。";
        if(phase.equals("ready_to_open")||phase.equals("waiting_lobby")||phase.equals("loading")||phase.equals("starting"))message+="\n悬浮进度卡会陪同加载，确认实际步进后自动收起；此时尚不是播放成功。";
        return message;
    }
    private static String clock(long tick){long sec=Math.max(0,tick/20);return String.format(Locale.ROOT,"%d:%02d",sec/60,sec%60);}
    private PlaybackStatus(){}
}
