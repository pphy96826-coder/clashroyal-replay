package local.royale.replay.android;

import java.io.*;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;

/** Saved source selection is independent of a native process/task lease. */
final class SavedReplay {
    static synchronized JSONObject metadata(File files)throws Exception{
        File source=new File(files,"source.html"),meta=new File(files,"source.json");
        if(!source.isFile()||!meta.isFile())return null;
        JSONObject value=new JSONObject(MainActivity.text(meta,8192));
        String hash=value.optString("sha256","");
        if(!hash.matches("[a-f0-9]{64}"))throw new IOException("保存的回放缺少校验信息");
        File hidden=new File(files,"saved-replay-hidden.json");
        if(hidden.isFile()&&hash.equals(new JSONObject(MainActivity.text(hidden,8192)).optString("sha256","")))return null;
        return value;
    }
    static synchronized byte[] load(File files,String expected)throws Exception{
        JSONObject meta=metadata(files);
        if(meta==null||!expected.equals(meta.optString("sha256","")))throw new IOException("已选回放发生变化，请重新确认");
        byte[] bytes=MainActivity.read(new FileInputStream(new File(files,"source.html")),ReplaySource.MAX_BYTES);
        if(!MainActivity.sha(bytes).equals(expected))throw new IOException("保存的 HTML 校验不符，请重新选择文件");
        MainActivity.checkedSource(bytes);
        return bytes;
    }
    static synchronized void hide(File files,String expected)throws Exception{
        JSONObject meta=metadata(files);
        if(meta==null||!expected.equals(meta.optString("sha256","")))throw new IOException("回放已变化，未移除其他文件");
        // Recoverable removal from the selection only. Never delete task receipts,
        // native owners, source files or the evidence needed for safe cleanup.
        MainActivity.write(new File(files,"saved-replay-hidden.json"),new JSONObject().put("sha256",expected)
            .put("removed_at",System.currentTimeMillis()/1000).toString().getBytes(StandardCharsets.UTF_8));
    }
    static synchronized void save(File files,byte[] bytes,ReplaySource.Info parsed)throws Exception{
        MainActivity.write(new File(files,"source.html"),bytes);
        MainActivity.write(new File(files,"source.json"),new JSONObject().put("tag",parsed.tag).put("events",parsed.count())
            .put("sha256",MainActivity.sha(bytes)).put("fixture",false).toString().getBytes(StandardCharsets.UTF_8));
        MainActivity.write(new File(files,"saved-replay-hidden.json"),new JSONObject().put("sha256","").toString().getBytes(StandardCharsets.UTF_8));
    }
    private SavedReplay(){}
}
