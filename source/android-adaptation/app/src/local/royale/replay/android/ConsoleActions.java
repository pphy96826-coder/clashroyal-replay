package local.royale.replay.android;

import android.content.Context;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Actions shared by the console Activity and the floating console; same gates for both.
 *
 * The first queue row is prepared ahead (calibration, full simulation and JSON
 * round-trip in the current game process) and parked at ready_to_open. Playing
 * it only adds the foreground handoff and scene load. Early preparation never
 * publishes a scene; changing the queue cancels it at the pre-scene boundary.
 */
final class ConsoleActions {
    static final double[] SPEEDS={.25,.5,1,2,4};
    static volatile int speedIndex=2;
    // True while the queue head is handed to PlaybackService; queue edits wait.
    private static volatile boolean starting;
    // Queue row the user asked to play; the service opens it once it is ready.
    private static volatile String playWhenReady="";
    // Rows whose early preparation ended without playing, and the game process it ran in:
    // automatic preparation is tried once per row per game process, never in a loop.
    private static final Map<String,String> outcomes=new HashMap<String,String>();
    private static final Map<String,Long> tried=new HashMap<String,Long>();
    private static volatile boolean importRequested;
    static synchronized void resetIntents(){playWhenReady="";importRequested=false;switchRequested=false;tried.clear();outcomes.clear();}
    static void awaitReset()throws Exception{
        long deadline=System.currentTimeMillis()+10000;
        while(starting&&System.currentTimeMillis()<deadline)Thread.sleep(100);
        if(starting)throw new IOException("队列准备线程仍在结束；重置标记已保留，请稍后再点重置");
    }
    static void imported(Context context){
        if(ReplayReset.blocked(context))return;
        importRequested=true;
        try{setAutomatic(context,true);}catch(Exception ignored){}
        SourcePreparation.schedule(context);autoPrepareLater(context);
    }
    static void setAutomatic(Context context,boolean on)throws Exception{
        MainActivity.write(new File(context.getFilesDir(),"queue-auto-prepare.json"),new JSONObject().put("enabled",on).toString().getBytes(StandardCharsets.UTF_8));
    }
    private static boolean automatic(Context context){
        try{return new JSONObject(MainActivity.text(new File(context.getFilesDir(),"queue-auto-prepare.json"),4096)).optBoolean("enabled",false);}catch(Exception e){return false;}
    }
    static boolean autoPreparationAllowed(JSONObject state){
        String phase=state.optString("state","");
        if(phase.equals("complete"))return state.optBoolean("client_reopened",false)&&state.optBoolean("generation_released",false)&&!state.optBoolean("monitor_active",true);
        return !state.optBoolean("generation_released",false)&&!state.optBoolean("terminal_choice_confirmed",false)&&!(phase.equals("complete")||phase.equals("cancelled")||phase.equals("stopped")||phase.equals("failed_recovered")||phase.equals("failed_before_native")||phase.equals("released"));
    }
    static double speed(){return SPEEDS[speedIndex];}
    static String speedLabel(){return "播放倍速："+SPEEDS[speedIndex]+"×";}
    /** Applies to rows prepared from now on; a row already prepared keeps its speed (shown on the row). */
    static void cycleSpeed(){speedIndex=(speedIndex+1)%SPEEDS.length;}
    // Set when the user explicitly replaces a prepared row; its game process is then restarted.
    private static volatile boolean switchRequested;
    private static volatile long removeArmedUntil;
    /**
     * A preparation cancelled after native entry is only released with its game
     * process (runtime rule). Restart the client, but only while it is still that
     * task's exact process (pid + start time); never touch another generation.
     */
    private static void restartForRelease(Context context,JSONObject state)throws Exception{
        if(!state.optBoolean("native_entry_started",false)||state.optLong("game_pid",0)<=0||!NativePython.sameGameGeneration(state))return;
        StandaloneDoctor.root("am force-stop "+StandaloneDoctor.GAME,15);
        for(int i=0;i<20&&!NativePython.gameGenerationReleased(state);i++)Thread.sleep(500);
        if(!NativePython.gameGenerationReleased(state))throw new IOException("游戏旧进程仍在，未切换");
        NativePython.recordRelease(context,state);
        PlaybackService.openGame(context);
        FloatingConsole.note(context,"已重启游戏客户端以释放上一份准备；进入大厅后自动准备"+(playWhenReady.isEmpty()?"队列第一场。":"并开播。"));
    }
    /** The active task's own runtime status (not the UI merge, where a newer request error may hide it). */
    private static JSONObject taskStatus(Context context){
        try{return new JSONObject(MainActivity.text(new File(PlaybackStatus.activeDirectory(context),"status.json"),32768));}catch(Exception e){return new JSONObject();}
    }
    private static boolean blockedByCancelledPreparation(JSONObject state)throws Exception{
        return state.optString("state","").equals("cancelled")&&state.optBoolean("native_entry_started",false)
            &&state.optLong("game_pid",0)>0&&NativePython.sameGameGeneration(state);
    }
    /** Explicit replacement of a prepared row: cancel at the pre-scene boundary, then restart its client. */
    private static void switchFrom(String armed){switchRequested=true;PlaybackService.cancelArmed(armed);}
    static boolean starting(){return starting;}
    static String playWhenReady(){return playWhenReady;}
    static boolean canPlayNext(JSONObject state)throws Exception{
        boolean complete=state.optString("state","").equals("complete");
        return !starting&&(PlaybackService.armedIdle()||(!PlaybackService.isBusy()&&(complete||!PlaybackStatus.ownsTask(state))));
    }
    private static long gamePid(){
        try{StandaloneDoctor.Output out=StandaloneDoctor.root("pidof "+StandaloneDoctor.GAME,5);String first=out.text.trim().split("\\s+")[0];
            return out.code==0&&first.matches("\\d{1,9}")?Long.parseLong(first):0;}catch(Exception e){return 0;}
    }
    /**
     * Off the UI thread. Starts preparing the first queue row. Automatic calls only
     * run with the game open and a released previous task; an explicit tap may also
     * finish a verified terminal first, as before.
     */
    private static void prepareHead(Context context,boolean user)throws Exception{
        if(ReplayReset.blocked(context)){if(user)throw new IOException("请先完成回放进程重置");return;}
        synchronized(ConsoleActions.class){
            if(starting||PlaybackService.isBusy()){if(user)throw new IOException("已有本机任务正在处理");return;}
            starting=true;
        }
        String id="";
        try{
            JSONArray rows=ReplayQueue.rows(context.getFilesDir());
            if(rows.length()==0){if(user)throw new IOException("队列为空");return;}
            id=rows.getJSONObject(0).getString("id");
            long pid=0;
            if(!user){
                pid=gamePid();if(pid<=0)return;
                synchronized(ConsoleActions.class){Long before=tried.get(id);if(before!=null&&before==pid)return;}
            }
            JSONObject state=PlaybackStatus.read(context);
            if(!user&&(!automatic(context)||(!autoPreparationAllowed(state)&&!(importRequested&&state.optString("state","").equals("idle")))))return;
            if(state.optString("state","").equals("complete")){
                boolean reopened=state.optBoolean("client_reopened",false);
                if(!user&&!reopened)return; // Only an explicit tap may close a client still showing the terminal.
                CompletedReplay.remember(context,PlaybackStatus.activeDirectory(context));
                NativePython.finishCompleted(context,state);
                if(!reopened)PlaybackService.openGame(context);
            }else if(PlaybackStatus.ownsTask(state)){if(user)throw new IOException("当前任务尚未完成，不覆盖战斗");return;}
            else if(blockedByCancelledPreparation(taskStatus(context))){
                // Automatic runs never restart the game; an explicit play tap may.
                if(!user){synchronized(ConsoleActions.class){tried.put(id,pid);outcomes.put(id,"上一份准备待释放");}return;}
                restartForRelease(context,taskStatus(context));
            }
            synchronized(ConsoleActions.class){tried.put(id,pid);outcomes.remove(id);}
            byte[] source=ReplayQueue.next(context.getFilesDir());
            importRequested=false;
            PlaybackService.begin(context,source,speed(),false,ReplayQueue.diagnostic(context.getFilesDir()),id);
        }catch(Exception e){
            if(!id.isEmpty())synchronized(ConsoleActions.class){outcomes.put(id,"未准备："+e.getMessage());}
            throw e;
        }finally{starting=false;}
    }
    /** Any thread; errors stay on the row, the user can still tap play. */
    static void autoPrepare(Context context){try{prepareHead(context,false);}catch(Exception ignored){}}
    static void autoPrepareLater(final Context context){new Thread(new Runnable(){public void run(){autoPrepare(context);}}).start();}
    /** Called by the service the moment the user's play request reaches a ready row. */
    static void armedStarted(Context context,String queueId,byte[] source){
        synchronized(ConsoleActions.class){if(queueId.equals(playWhenReady))playWhenReady="";outcomes.remove(queueId);tried.remove(queueId);}
        try{ReplayQueue.consumeId(context.getFilesDir(),queueId);MainActivity.saveSource(context,source,MainActivity.checkedSource(source));}catch(Exception ignored){}
    }
    static void armedEnded(Context context,String queueId,boolean played,boolean cancelled,String title){
        if(queueId.isEmpty())return;
        boolean wanted;
        synchronized(ConsoleActions.class){
            wanted=queueId.equals(playWhenReady);
            if(played||cancelled){outcomes.remove(queueId);tried.remove(queueId);}
            else{outcomes.put(queueId,title);if(wanted)playWhenReady="";}
        }
        if(cancelled&&switchRequested){
            switchRequested=false;
            try{restartForRelease(context,taskStatus(context));}catch(Exception e){FloatingConsole.note(context,"切换未完成："+e.getMessage());}
        }
        if(wanted&&!played&&!cancelled)FloatingConsole.note(context,"未能开播："+title+"。可再点“播放下一个”重新准备。");
    }
    /** Off the UI thread. Plays the first queue row: at once if prepared, otherwise after preparing. */
    static String playNext(Context context)throws Exception{
        JSONArray rows=ReplayQueue.rows(context.getFilesDir());if(rows.length()==0)throw new IOException("队列为空");
        String head=rows.getJSONObject(0).getString("id");
        synchronized(ConsoleActions.class){
            if(PlaybackService.isBusy()){
                String armed=PlaybackService.armedQueueId();
                if(armed.isEmpty())throw new IOException("当前回放尚未结束，不覆盖战斗");
                playWhenReady=head;
                if(armed.equals(head))return "已提前准备，马上开播。";
                switchFrom(armed);
                return "正在切换到这一场：先重启游戏客户端释放上一份准备，约 1 分钟后开播。";
            }
            playWhenReady=head;
        }
        try{prepareHead(context,true);}catch(Exception e){playWhenReady="";throw e;}
        return "正在准备这一场；完成后自动开播。";
    }
    /** Off the UI thread. A browser replay the user chose to play now: it goes to the front of the queue. */
    static String playOffer(Context context,byte[] source)throws Exception{
        ReplaySource.Info parsed=MainActivity.checkedSource(source);
        JSONObject state=PlaybackStatus.read(context);
        boolean complete=state.optString("state","").equals("complete");
        String id=ReplayQueue.add(context.getFilesDir(),source,parsed);
        if((PlaybackService.isBusy()&&!PlaybackService.armedIdle())||(!PlaybackService.isBusy()&&PlaybackStatus.ownsTask(state)&&!complete))
            {imported(context);return "已加入待播队列（"+parsed.tag+"）；当前回放保持不变。";}
        ReplayQueue.moveTo(context.getFilesDir(),id,0);
        SourcePreparation.schedule(context);
        return playNext(context);
    }
    /**
     * Off the UI thread. Replay this match / exit after a verified terminal. Replay
     * re-reads this task's own HTML and checks its SHA-256; never substitutes another file.
     * If the next row is already being prepared, "replay" puts the last played match first.
     */
    static String finishReplay(Context context,boolean again,boolean reopenAfterExit)throws Exception{
        if(!again){setAutomatic(context,false);importRequested=false;CompletedReplay.dismiss(context);}
        if(PlaybackService.armedIdle()){
            if(!again)return "已退出上一场；下一场保留为待播，不会自动开播。";
            byte[] source=CompletedReplay.source(context);
            ReplayQueue.moveTo(context.getFilesDir(),ReplayQueue.add(context.getFilesDir(),source,MainActivity.checkedSource(source)),0);
            return playNext(context);
        }
        synchronized(ConsoleActions.class){if(starting||PlaybackService.isBusy())throw new IOException("已有本机任务正在处理");starting=true;}
        try{
            JSONObject state=PlaybackStatus.read(context);
            byte[] source=null;
            if(state.optString("state","").equals("complete")){
                File directory=PlaybackStatus.activeDirectory(context);
                if(again){
                    source=MainActivity.read(new FileInputStream(new File(directory.getParentFile().getParentFile(),"input.html")),ReplaySource.MAX_BYTES);
                    if(!MainActivity.sha(source).equals(state.optString("source_sha256","")))throw new IOException("本场原始 HTML 校验不符，未使用其他文件重放");
                }
                NativePython.finishCompleted(context,state);
                if(again||reopenAfterExit)PlaybackService.openGame(context);
            }else{
                if(!again||PlaybackStatus.ownsTask(state))throw new IOException("旧任务仍需安全核验，未覆盖游戏现场");
                source=CompletedReplay.source(context);
            }
            if(again)PlaybackService.begin(context,source,speed(),true);
            return again?"正在重放；校验通过后自动在游戏里开播。":"已退出回放"+(reopenAfterExit?"，游戏已重新打开。":"。");
        }finally{starting=false;}
    }
    static void requestStop(Context context)throws Exception{
        JSONObject state=PlaybackStatus.read(context);
        if(!PlaybackStatus.canStop(state,System.currentTimeMillis()/1000))throw new IOException("观察已结束或状态过期；未执行重启，请先检查游戏现场");
        File directory=PlaybackStatus.activeDirectory(context);
        MainActivity.write(new File(directory,"stop-request.json"),new JSONObject().put("user_requested_client_only_restart",true).toString().getBytes(StandardCharsets.UTF_8));
    }
    /** After a queue edit: start preparing the (new) first row if nothing is prepared yet. */
    private static void queueChanged(Context context)throws Exception{
        String armed=PlaybackService.armedQueueId();
        JSONArray rows=ReplayQueue.rows(context.getFilesDir());
        if(!armed.isEmpty()&&(rows.length()==0||!armed.equals(rows.getJSONObject(0).getString("id"))))switchFrom(armed);
        else if(!PlaybackService.isBusy())autoPrepareLater(context);
    }
    static synchronized void removeQueued(Context context,String id)throws Exception{
        if(starting)throw new IOException("下一场正在开始，稍后再改队列");
        if(id.equals(PlaybackService.armedQueueId())&&System.currentTimeMillis()>removeArmedUntil){
            removeArmedUntil=System.currentTimeMillis()+5000;
            throw new IOException("这一场已提前准备好；删除需要重启游戏客户端来释放。5 秒内再点一次「删除」确认");
        }
        removeArmedUntil=0;
        ReplayQueue.remove(context.getFilesDir(),id);outcomes.remove(id);queueChanged(context);
    }
    /** The prepared row stays first; 置顶 on another row makes it the one right after. */
    static synchronized void moveQueuedToFront(Context context,String id)throws Exception{
        if(starting)throw new IOException("下一场正在开始，稍后再改队列");
        String armed=PlaybackService.armedQueueId();
        ReplayQueue.moveTo(context.getFilesDir(),id,!armed.isEmpty()&&!armed.equals(id)?1:0);queueChanged(context);
    }
    static synchronized int clearQueue(Context context)throws Exception{
        if(starting)throw new IOException("下一场正在开始，稍后再改队列");
        int cleared=ReplayQueue.clear(context.getFilesDir());outcomes.clear();queueChanged(context);return cleared;
    }
    /** Headline while a row is only prepared ahead (nothing is playing); null otherwise. */
    static String[] earlyStatus(JSONObject state){
        if(!PlaybackService.armedIdle())return null;
        String phase=state.optString("state",""),armed=PlaybackService.armedQueueId();
        boolean wanted=armed.equals(playWhenReady);
        if(phase.equals("ready_to_open")){
            String match=pageMatch(state),tried="已试 "+state.optLong("seed_attempts",0)+" 个随机种子";
            String check=match.equals("same_towers")?"胜负和被摧毁的塔与网页一致，塔血合计相差 "+state.optLong("page_hp_difference",0)+"（"+tried+"，选最接近的）。"
                :match.equals("same_winner")?"⚠ 胜负与网页一致，但被摧毁的塔不同（"+tried+"）。"
                :match.equals("different")?"⚠ 终局与网页不符（"+tried+"），过程与原局不同。"
                :state.optBoolean("random_seed_inferred",false)?"换用随机种子后终局塔血与网页完全一致。":"终局塔血与网页完全一致。";
            String versionHint=(match.equals("same_towers")||match.equals("same_winner")||match.equals("different"))
                ?state.optString("version_check_hint","请先检查游戏客户端版本及回放日期，确认是否跨越平衡性调整；版本或战斗参数变化可能造成差异，不能仅据此归因于随机种子或技能目标。") :"";
            return new String[]{"下一场已就绪",check+state.optString("page_match_detail","")+versionHint+"点「播放下一个」即可在游戏里开播；游戏客户端不重启时约 2 小时内有效。"};
        }
        if(phase.equals("simulating"))return new String[]{state.optBoolean("seed_search_active",false)?"正在筛选种子和技能分支":"正在匹配技能分支",PlaybackStatus.detail(state,System.currentTimeMillis()/1000)};
        if(phase.equals("calibrating")||phase.equals("validating"))return new String[]{PlaybackStatus.title(state),PlaybackStatus.detail(state,System.currentTimeMillis()/1000)};
        if(phase.equals("waiting_preparation_lobby"))return new String[]{"等待游戏前台大厅",state.optString("message","")};
        return new String[]{wanted?"准备中 · 完成后自动开播":"正在提前准备下一场",
            (phase.equals("calibrating")?"校准原生发牌":phase.equals("simulating")?"预演整局":phase.equals("validating")?"核对全部指令":"读取资源并等待大厅")+(wanted?"；不用再点。":"；只做准备，不会自动开播。")};
    }
    /** exact / same_towers / same_winner / different; older records only know exact-or-not. */
    static String pageMatch(JSONObject state){
        return state.optString("page_match",state.optBoolean("final_hp_matched",true)?"exact":"different");
    }
    static String readyLabel(JSONObject state){
        String match=pageMatch(state);
        return match.equals("exact")?"✓ 已就绪":match.equals("same_towers")?"✓ 已就绪·终局近似":match.equals("same_winner")?"⚠ 已就绪·仅胜负同网页":"⚠ 已就绪·与网页不符";
    }
    static boolean canAcceptBest(JSONObject state,long now){
        long age=now-state.optLong("updated_at",0);
        String phase=state.optString("state","");
        return (phase.equals("simulating")||phase.equals("waiting_preparation_lobby"))&&state.optBoolean("seed_search_active",false)
            &&state.optBoolean("best_source_execution_verified",false)&&state.optBoolean("monitor_active",false)
            &&state.optString("source_sha256","").matches("[a-f0-9]{64}")&&state.optLong("game_pid",0)>0
            &&!state.optString("game_start_time","").isEmpty()&&age>=0&&age<=300;
    }
    static boolean bestRequestPending(Context context){try{return new File(PlaybackStatus.activeDirectory(context),"accept-best-seed.json").isFile();}catch(Exception e){return false;}}
    static String acceptBest(Context context)throws Exception{
        if(!PlaybackService.isBusy())throw new IOException("当前没有正在匹配的任务");
        File directory=PlaybackStatus.activeDirectory(context);
        JSONObject request=new JSONObject(MainActivity.text(new File(context.getFilesDir(),"phone-service-state.json"),32768));
        JSONObject state=new JSONObject(MainActivity.text(new File(directory,"status.json"),32768));
        if(!directory.getAbsolutePath().equals(request.optString("directory",""))||!state.optString("source_sha256","").equals(request.optString("source_sha256","missing"))
            ||!canAcceptBest(state,System.currentTimeMillis()/1000)||!NativePython.sameGameGeneration(state))throw new IOException("尚无可播放的完整结果，或当前任务已变化");
        JSONObject signal=new JSONObject().put("schema","royale-replay.accept-best-seed.v1").put("source_sha256",state.getString("source_sha256"))
            .put("game_pid",state.getLong("game_pid")).put("game_start_time",state.getString("game_start_time")).put("play_best",true).put("created_at",System.currentTimeMillis()/1000);
        MainActivity.write(new File(directory,"accept-best-seed.json"),signal.toString().getBytes(StandardCharsets.UTF_8));
        synchronized(ConsoleActions.class){if(PlaybackService.armedIdle())playWhenReady=PlaybackService.armedQueueId();}
        try{PlaybackService.openGame(context);}catch(Exception e){return "停止请求已保存；请打开游戏大厅，核验后播放当前最优。";}
        return "已请求停止匹配；当前原生步骤安全结束后，核验并播放已完整执行的最优对局。终局可能与网页不同。";
    }
    /** Short status for each queue row, shown on the right of the row. */
    static Map<String,String> rowStatus(Context context,JSONArray rows){
        Map<String,String> result=new HashMap<String,String>();
        String armed=PlaybackService.armedQueueId(),phase="";JSONObject armedState=new JSONObject();
        if(!armed.isEmpty())try{armedState=PlaybackStatus.read(context);phase=armedState.optString("state","");}catch(Exception ignored){}
        for(int i=0;i<rows.length();i++){
            String id=rows.optJSONObject(i)==null?"":rows.optJSONObject(i).optString("id","");
            String label;
            if(id.equals(armed)){
                String at=PlaybackService.armedSpeed()==speed()?"":"("+PlaybackService.armedSpeed()+"×)";
                if(phase.equals("ready_to_open"))label=id.equals(playWhenReady)?"正在开播":readyLabel(armedState)+at;
                else if(armedState.optString("message","").contains("随机种子"))label="准备中·匹配随机种子";
                else if(phase.equals("calibrating"))label="准备中·校准发牌";
                else if(phase.equals("simulating"))label="准备中·预演整局";
                else if(phase.equals("validating"))label="准备中·核对指令";
                else if(phase.equals("waiting_preparation_lobby"))label="等待游戏前台大厅";
                else label="准备中·读取资源";
            }else synchronized(ConsoleActions.class){
                if(outcomes.containsKey(id))label="未就绪·播放时重新准备";
                else label=SourcePreparation.stage(id)+(i==0?" · 等待原生准备":" · 等待前一场");
            }
            result.put(id,label);
        }
        return result;
    }
    private ConsoleActions(){}
}
