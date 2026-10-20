package local.royale.replay.android;

import android.content.Context;
import java.io.*;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;

/** Actions shared by the console Activity and the floating console; same gates for both. */
final class ConsoleActions {
    static final double[] SPEEDS={.25,.5,1,2,4};
    static volatile int speedIndex=2;
    // True while the queue head is handed to PlaybackService; queue edits wait.
    private static volatile boolean starting;
    static double speed(){return SPEEDS[speedIndex];}
    static String speedLabel(){return "播放倍速："+SPEEDS[speedIndex]+"×";}
    static void cycleSpeed(){speedIndex=(speedIndex+1)%SPEEDS.length;}
    static boolean starting(){return starting;}
    static boolean canPlayNext(JSONObject state)throws Exception{
        boolean complete=state.optString("state","").equals("complete");
        return !starting&&!PlaybackService.isBusy()&&(complete||!PlaybackStatus.ownsTask(state));
    }
    /** Called off the UI thread. Never overwrites a task that still owns the scene. */
    static void playNext(Context context)throws Exception{
        synchronized(ConsoleActions.class){if(starting||PlaybackService.isBusy())throw new IOException("已有本机任务正在处理");starting=true;}
        try{
            JSONObject state=PlaybackStatus.read(context);
            byte[] source=ReplayQueue.next(context.getFilesDir());
            if(state.optString("state","").equals("complete")){NativePython.finishCompleted(context,state);PlaybackService.openGame(context);}
            else if(PlaybackStatus.ownsTask(state))throw new IOException("当前任务尚未完成，不覆盖战斗");
            ReplaySource.Info parsed=MainActivity.checkedSource(source);MainActivity.saveSource(context,source,parsed);
            PlaybackService.begin(context,source,speed(),true,ReplayQueue.diagnostic(context.getFilesDir()));
            ReplayQueue.consume(context.getFilesDir(),MainActivity.sha(source));
        }finally{starting=false;}
    }
    static void requestStop(Context context)throws Exception{
        JSONObject state=PlaybackStatus.read(context);
        if(!PlaybackStatus.canStop(state,System.currentTimeMillis()/1000))throw new IOException("观察已结束或状态过期；未执行重启，请先检查游戏现场");
        File directory=PlaybackStatus.activeDirectory(context);
        MainActivity.write(new File(directory,"stop-request.json"),new JSONObject().put("user_requested_client_only_restart",true).toString().getBytes(StandardCharsets.UTF_8));
    }
    static synchronized void removeQueued(Context context,String id)throws Exception{
        if(starting)throw new IOException("下一场正在开始，稍后再改队列");
        ReplayQueue.remove(context.getFilesDir(),id);
    }
    static synchronized void moveQueuedToFront(Context context,String id)throws Exception{
        if(starting)throw new IOException("下一场正在开始，稍后再改队列");
        ReplayQueue.moveToFront(context.getFilesDir(),id);
    }
    static synchronized int clearQueue(Context context)throws Exception{
        if(starting)throw new IOException("下一场正在开始，稍后再改队列");
        return ReplayQueue.clear(context.getFilesDir());
    }
    private ConsoleActions(){}
}
