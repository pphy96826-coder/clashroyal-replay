package local.royale.replay.android;

import android.content.Context;
import java.io.*;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;

/** End-of-match controls survive preparation of the next queue row. */
final class CompletedReplay {
    static void remember(Context context,File directory)throws Exception{
        directory=PrivateTaskPaths.resolve(context.getFilesDir(),directory,false);
        JSONObject state=new JSONObject(MainActivity.text(new File(directory,"status.json"),32768));
        if(state.optBoolean("monitor_active",true)||!PlaybackStatus.completedVerified(directory,state))throw new IOException("终局尚未核验");
        MainActivity.write(new File(context.getFilesDir(),"last-completed.json"),new JSONObject().put("directory",directory.getAbsolutePath())
            .put("source_sha256",state.getString("source_sha256")).put("dismissed",false).toString().getBytes(StandardCharsets.UTF_8));
    }
    static JSONObject metadata(Context context)throws Exception{
        File file=new File(context.getFilesDir(),"last-completed.json");if(!file.isFile())return null;
        JSONObject record=new JSONObject(MainActivity.text(file,8192));if(record.optBoolean("dismissed",false))return null;
        File directory=PrivateTaskPaths.resolve(context.getFilesDir(),new File(record.getString("directory")),false);
        JSONObject state=new JSONObject(MainActivity.text(new File(directory,"status.json"),32768));
        if(!record.optString("source_sha256","").equals(state.optString("source_sha256","missing"))||!PlaybackStatus.completedVerified(directory,state))throw new IOException("上一场记录不一致");
        return record;
    }
    static byte[] source(Context context)throws Exception{
        JSONObject record=metadata(context);
        if(record==null){JSONObject saved=SavedReplay.metadata(context.getFilesDir());if(saved==null)throw new IOException("没有已保存回放");return SavedReplay.load(context.getFilesDir(),saved.getString("sha256"));}
        File directory=new File(record.getString("directory"));
        byte[] source=MainActivity.read(new FileInputStream(new File(directory.getParentFile().getParentFile(),"input.html")),ReplaySource.MAX_BYTES);
        if(!MainActivity.sha(source).equals(record.getString("source_sha256")))throw new IOException("上一场 HTML 校验失败");MainActivity.checkedSource(source);return source;
    }
    static void dismiss(Context context)throws Exception{
        JSONObject value=metadata(context);if(value!=null)MainActivity.write(new File(context.getFilesDir(),"last-completed.json"),value.put("dismissed",true).toString().getBytes(StandardCharsets.UTF_8));
    }
}
