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
    // Rows whose automatic preparation failed (not cancelled). Failure recovery may
    // restart the game, so a per-process guard alone would retry them in a loop.
    private static final java.util.Set<String> autoFailed=new java.util.HashSet<String>();
    static double speed(){return SPEEDS[speedIndex];}
    /** Seed search in progress: the user ends it and plays the closest result found so far. */
    static boolean seedSearching(JSONObject state){return state.optString("state","").equals("simulating")&&state.optBoolean("seed_search_active",false);}
    /** Hunter/Skeleton King decks: closest ability combination search (before seeds). */
    static boolean abilityMatching(JSONObject state){return state.optBoolean("ability_search_active",false);}
    static String stopSeedSearch(Context context)throws Exception{
        File stop=new File(PlaybackStatus.activeDirectory(context),"seed-stop-request.json");
        if(!stop.exists())MainActivity.write(stop,new JSONObject().put("use_closest_so_far",true).put("requested_at",System.currentTimeMillis()/1000).toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
        return "已请求停止匹配：当前这次预演跑完后（最多约十几秒）用最接近的结果继续校验并开播。";
    }
    /**
     * Failsafe chosen explicitly by the user (two taps): stop every replay runner,
     * force-stop the game (the kernel drops a dead tracer; a fresh process has no
     * replay component), then archive the active-task pointer. History, queue and
     * diagnostics files are kept; nothing is deleted.
     */
    static String resetAll(Context context)throws Exception{
        // [e] keeps the pattern from matching the shell that runs it.
        String runners="pgrep -f 'libphone_runtim[e][.]so'";
        StandaloneDoctor.root("for p in $("+runners+"); do kill -9 $p; done",10);
        PlaybackService.resetAll(context);
        // A game left stopped (state T) by an interrupted debugger is first resumed
        // so force-stop can end it; this explicit failsafe may then kill it outright.
        String resume="for p in $(pidof "+StandaloneDoctor.GAME+"); do kill -CONT $p; done";
        StandaloneDoctor.root(resume+"; am force-stop "+StandaloneDoctor.GAME,15);
        for(int i=0;i<20;i++){
            StandaloneDoctor.Output left=StandaloneDoctor.root(runners+" || true",5);
            StandaloneDoctor.Output game=StandaloneDoctor.root("pidof "+StandaloneDoctor.GAME+" || printf NONE",5);
            if(left.code==0&&left.text.trim().isEmpty()&&game.text.trim().equals("NONE"))break;
            if(i==6)StandaloneDoctor.root("for p in $(pidof "+StandaloneDoctor.GAME+"); do kill -CONT $p; kill -9 $p; done",10);
            if(i==19)throw new IOException("仍有回放进程或游戏未退出；请稍后再点一次");
            Thread.sleep(500);
        }
        long now=System.currentTimeMillis()/1000;
        File active=new File(context.getFilesDir(),"phone-active.json");
        if(active.isFile()&&!active.renameTo(new File(context.getFilesDir(),"phone-active.reset-"+now+".json")))throw new IOException("无法归档当前任务记录");
        MainActivity.write(new File(context.getFilesDir(),"phone-service-state.json"),new org.json.JSONObject().put("state","idle").put("updated_at",now)
            .put("message","已重置：所有回放进程已结束，游戏已关闭。队列和历史记录保留；打开游戏进入大厅后可重新播放。").toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
        synchronized(ConsoleActions.class){starting=false;}
        playWhenReady="";switchRequested=false;outcomes.clear();tried.clear();autoFailed.clear();
        return "已重置所有回放进程并关闭游戏；队列保留。重新打开游戏进入大厅后再播放。";
    }
    /**
     * Some VM ROMs (seen in 虚拟大师 Android 12) spin their fingerprint HAL at a full
     * core forever, which starves the game. Freeze ONLY that service (SIGSTOP), and
     * only while it is really busy (>=50% of a core over 2 s). It is never stopped or
     * killed: 虚拟大师's health monitor treats a dead HAL as a core-process crash.
     * A frozen HAL uses no CPU; settings stay untouched and the next VM boot resets it.
     */
    static final String FINGERPRINT_HAL="android.hardware.biometrics.fingerprint@2.1-service";
    static String stopBusyFingerprint()throws Exception{
        String script="p=$(pidof "+FINGERPRINT_HAL+"); [ -z \"$p\" ] && { echo NONE; exit 0; }; "
            +"[ \"$(awk '{print $3}' /proc/$p/stat)\" = T ] && { echo FROZEN; exit 0; }; "
            +"t(){ awk '{print $14+$15}' /proc/$p/stat 2>/dev/null || echo 0; }; a=$(t); sleep 2; b=$(t); echo BUSY $((b-a)); "
            +"[ $((b-a)) -lt 100 ] && exit 0; "
            +"kill -STOP $p 2>&1; sleep 1; "
            +"if [ -d /proc/$p ]; then echo STATE $(awk '{print $3}' /proc/$p/stat); else echo GONE; fi";
        String out=StandaloneDoctor.root(script,15).text;
        if(out.contains("NONE"))return "未发现指纹服务进程；无需处理。";
        if(out.contains("FROZEN"))return "指纹服务已处于冻结状态（不占用 CPU）；无需处理。";
        java.util.regex.Matcher busy=java.util.regex.Pattern.compile("BUSY (\\d+)").matcher(out);
        int ticks=busy.find()?Integer.parseInt(busy.group(1)):-1;
        if(ticks>=0&&ticks<100)return "指纹服务当前不忙（2 秒内占用约 "+ticks/2+"% 单核）；未处理。";
        if(out.contains("STATE T"))return "已冻结卡住的指纹服务（不再占用 CPU，进程保留，不会触发虚拟机崩溃提示）；虚拟机重启后恢复。";
        return "未能冻结指纹服务。原始结果："+out.trim().replace('\n',' ');
    }
    /**
     * Explicit two-tap cleanup, refused while any replay runner exists. Removes what
     * earlier console builds and finished tasks left behind: runtime folders of other
     * builds, task records except the active task, tool self-checks, and staged
     * component copies in /data/local/tmp that the game no longer maps. Queue, saved
     * replay, settings and the current runtime are kept.
     */
    static String cleanStorage(Context context)throws Exception{
        File files=context.getFilesDir();String path=files.getAbsolutePath();
        if(!path.matches("/data/(user/0|data)/local[.]royale[.]replay[.]android/files"))throw new IOException("控制台数据目录异常；未清理");
        String python=NativePython.runtimeFolder(context,"python-runtime.sha256","python-");
        String tools=NativePython.runtimeFolder(context,"android-tools.sha256","android-tools-");
        String task="none";
        try{java.util.regex.Matcher m=java.util.regex.Pattern.compile("local-imports/([a-f0-9-]{36})/").matcher(new JSONObject(MainActivity.text(new File(files,"phone-active.json"),8192)).optString("directory",""));if(m.find())task=m.group(1);}catch(Exception ignored){}
        String script="pgrep -f 'libphone_runtim[e][.]so' >/dev/null && { echo BUSY; exit 0; }; F="+path+"; "
            +"sz(){ du -sk $F /data/local/tmp 2>/dev/null | awk '{s+=$1}END{print s+0}'; }; b=$(sz); "
            +"for d in $F/python-* $F/android-tools-*; do [ -d \"$d\" ] || continue; n=${d##*/}; [ \"$n\" = "+python+" ] || [ \"$n\" = "+tools+" ] || rm -rf \"$d\"; done; "
            +"for d in $F/local-imports/*; do [ -d \"$d\" ] || continue; [ \"${d##*/}\" = "+task+" ] || rm -rf \"$d\"; done; "
            +"rm -rf $F/tool-checks; "
            +"g=$(pidof "+StandaloneDoctor.GAME+"); for d in /data/local/tmp/royale-phone-*; do [ -d \"$d\" ] || continue; [ -n \"$g\" ] && grep -q \"$d\" /proc/$g/maps && continue; rm -rf \"$d\"; done; "
            +"echo FREED $((b-$(sz)))";
        String out=StandaloneDoctor.root(script,120).text;
        if(out.contains("BUSY"))return "有回放正在准备或播放；为避免误删正在用的文件，未清理。请等结束或先重置再清理。";
        java.util.regex.Matcher freed=java.util.regex.Pattern.compile("FREED (-?\\d+)").matcher(out);
        if(!freed.find())throw new IOException("清理结果未知："+out.trim());
        long kb=Math.max(0,Long.parseLong(freed.group(1)));
        return "已清理旧运行环境和过期任务记录，释放约 "+(kb/1024)+" MB；队列、已保存回放和当前任务保留。";
    }
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
                synchronized(ConsoleActions.class){if(autoFailed.contains(id))return;}
                pid=gamePid();if(pid<=0)return;
                synchronized(ConsoleActions.class){Long before=tried.get(id);if(before!=null&&before==pid)return;}
            }else{synchronized(ConsoleActions.class){autoFailed.remove(id);}}
            if(user&&gamePid()<=0){
                // An explicit play with the game closed (reset, or a phone VM reclaimed it):
                // open it; the runner waits read-only for the idle lobby before any native step.
                PlaybackService.openGame(context);
                FloatingConsole.note(context,"游戏未运行：已自动打开游戏，进入大厅后开始准备（手机虚拟机约 1–3 分钟）。");
            }
            JSONObject state=PlaybackStatus.read(context);
            if(state.optString("state","").equals("complete")){
                boolean reopened=state.optBoolean("client_reopened",false);
                if(!user&&!reopened)return; // Only an explicit tap may close a client still showing the terminal.
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
            else{outcomes.put(queueId,title);autoFailed.add(queueId);if(wanted)playWhenReady="";}
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
            return "已加入待播队列（"+parsed.tag+"）；当前回放保持不变。";
        ReplayQueue.moveTo(context.getFilesDir(),id,0);
        return playNext(context);
    }
    /**
     * Off the UI thread. Replay this match / exit after a verified terminal. Replay
     * re-reads this task's own HTML and checks its SHA-256; never substitutes another file.
     * If the next row is already being prepared, "replay" puts the last played match first.
     */
    static String finishReplay(Context context,boolean again,boolean reopenAfterExit)throws Exception{
        if(PlaybackService.armedIdle()){
            if(!again)return "上一场已结束并释放；无需退出。";
            JSONObject saved=SavedReplay.metadata(context.getFilesDir());
            if(saved==null)throw new IOException("没有已保存回放");
            byte[] source=SavedReplay.load(context.getFilesDir(),saved.getString("sha256"));
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
                JSONObject saved=SavedReplay.metadata(context.getFilesDir());
                if(saved==null)throw new IOException("没有已保存回放");
                source=SavedReplay.load(context.getFilesDir(),saved.getString("sha256"));
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
            long attempts=state.optLong("seed_attempts",0);
            String match=pageMatch(state),tried=attempts>0?"已试 "+attempts+" 个随机种子，选取已完整执行的最接近结果"
                :!state.optBoolean("seed_search_allowed",true)?"卡组无骷髅之王或猎人，保留原种子，未搜索其他种子":"保留原种子，未搜索其他种子";
            String check=match.equals("same_towers")?"胜负和被摧毁的塔与网页一致，塔血合计相差 "+state.optLong("page_hp_difference",0)+"（"+tried+"）。"
                :match.equals("same_winner")?"⚠ 胜负与网页一致，但被摧毁的塔不同（"+tried+"）。"
                :match.equals("different")?"⚠ 终局与网页不符（"+tried+"），过程与原局不同。"
                :match.equals("unknown")?"终局有塔缺少网页数据或模拟记录，无法完整比对；未当作不一致。"
                :state.optBoolean("random_seed_inferred",false)?"换用随机种子后终局塔血与网页完全一致。":"终局塔血与网页完全一致。";
            String versionHint=(match.equals("same_towers")||match.equals("same_winner")||match.equals("different"))
                ?state.optString("version_check_hint","请先检查游戏客户端版本及回放日期，确认是否跨越平衡性调整；版本或战斗参数变化可能造成差异，不能仅据此归因于随机种子或技能目标。") :"";
            return new String[]{"下一场已就绪",check+state.optString("page_match_detail","")+versionHint+"点「播放下一个」约 15 秒开播；游戏客户端不重启时约 2 小时内有效。"};
        }
        if(seedSearching(state))return new String[]{abilityMatching(state)?"正在匹配技能目标":"正在匹配随机种子",state.optString("message","")};
        return new String[]{wanted?"准备中 · 完成后自动开播":"正在提前准备下一场",
            (phase.equals("calibrating")?"校准原生发牌":phase.equals("simulating")?"预演整局":phase.equals("validating")?"核对全部指令":"读取资源并等待大厅")+(wanted?"；不用再点。":"；只做准备，不会自动开播。")};
    }
    /** exact / same_towers / same_winner / different; older records only know exact-or-not. */
    static String pageMatch(JSONObject state){
        return state.optString("page_match",state.optBoolean("final_hp_matched",true)?"exact":"different");
    }
    static String readyLabel(JSONObject state){
        String match=pageMatch(state);
        return match.equals("exact")?"✓ 已就绪":match.equals("same_towers")?"✓ 已就绪·终局近似":match.equals("same_winner")?"⚠ 已就绪·仅胜负同网页":match.equals("unknown")?"✓ 已就绪·终局无法完整比对":"⚠ 已就绪·与网页不符";
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
                else if(seedSearching(armedState))label=abilityMatching(armedState)?"准备中·匹配技能目标":"准备中·匹配随机种子";
                else if(phase.equals("calibrating"))label="准备中·校准发牌";
                else if(phase.equals("simulating"))label="准备中·预演整局";
                else if(phase.equals("validating"))label="准备中·核对指令";
                else label="准备中·读取资源";
            }else synchronized(ConsoleActions.class){
                if(outcomes.containsKey(id))label="未就绪·播放时重新准备";
                else label=i==0?"等待准备":"排队中";
            }
            result.put(id,label);
        }
        return result;
    }
    private ConsoleActions(){}
}
