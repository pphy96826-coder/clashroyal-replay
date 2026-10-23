package local.royale.replay.android;

import android.content.Context;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import org.json.JSONObject;

/** One explicit action, shared by the full and floating consoles. */
final class ReplayReset {
    private static volatile boolean running;
    static boolean blocked(Context context){return running||new File(context.getFilesDir(),"reset-in-progress.json").isFile();}
    static String reset(Context context)throws Exception{
        synchronized(ReplayReset.class){if(running)throw new IOException("正在重置，请稍候");running=true;}
        try{
            ConsoleActions.setAutomatic(context,false);ConsoleActions.resetIntents();
            File parent=new File(context.getFilesDir(),"process-resets");if(!parent.isDirectory()&&!parent.mkdir())throw new IOException("无法创建重置记录");
            String id=UUID.randomUUID().toString();File action=new File(parent,id);if(!action.mkdir())throw new IOException("无法保存重置请求");
            JSONObject request=new JSONObject().put("schema","royale-replay.reset.v1").put("id",id).put("user_authorized",true);
            byte[] raw=request.toString().getBytes(StandardCharsets.UTF_8);
            File marker=new File(context.getFilesDir(),"reset-in-progress.json");
            MainActivity.write(new File(action,"request.json"),raw);MainActivity.write(marker,raw);
            JSONObject result=NativePython.resetProcesses(context,new File(action,"request.json"),new File(action,"reset-result"));
            if(!result.optBoolean("reset_completed",false))throw new IOException("重置未通过归属检查；记录已保留");
            PlaybackService.finishReset();
            ConsoleActions.awaitReset();
            if(PlaybackService.isBusy())throw new IOException("回放服务仍在结束；重置记录已保存，请稍后再点重置");
            String message="已重置所有回放进程，控制台已就绪。回放、队列和诊断记录已保留；自动准备已暂停。";
            if(result.optBoolean("game_restarted",false))message+="已重新打开游戏，请等待大厅加载。";
            MainActivity.write(new File(context.getFilesDir(),"phone-service-state.json"),new JSONObject().put("state","idle").put("monitor_active",false)
                .put("message",message).put("reset_id",id).put("updated_at",System.currentTimeMillis()/1000).toString().getBytes(StandardCharsets.UTF_8));
            if(!id.equals(new JSONObject(MainActivity.text(marker,4096)).optString("id",""))||!marker.delete())throw new IOException("重置标记发生变化；请查看记录");
            return message;
        }finally{running=false;}
    }
    private ReplayReset(){}
}
