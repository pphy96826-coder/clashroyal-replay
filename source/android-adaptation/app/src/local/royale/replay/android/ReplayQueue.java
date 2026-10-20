package local.royale.replay.android;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import org.json.JSONArray;
import org.json.JSONObject;

/** Pure HTML parsing/storage may run while PlaybackService owns native work. */
final class ReplayQueue {
    private static File directory(File files)throws IOException{
        File dir=new File(files,"replay-queue");
        if(!dir.isDirectory()&&!dir.mkdir())throw new IOException("无法创建队列目录");
        return dir;
    }
    static synchronized JSONArray rows(File files)throws Exception{
        File index=new File(directory(files),"index.json");
        return index.isFile()?new JSONArray(MainActivity.text(index,512*1024)):new JSONArray();
    }
    static synchronized void add(File files,byte[] source,ReplaySource.Info parsed)throws Exception{
        JSONArray rows=rows(files);long total=source.length;
        for(int i=0;i<rows.length();i++)total+=rows.getJSONObject(i).optLong("bytes",256L*1024*1024);
        if(rows.length()>=128||total>256L*1024*1024)throw new IOException("队列上限128场或256MB");
        String id=UUID.randomUUID().toString();File dir=directory(files);
        MainActivity.write(new File(dir,id+".html"),source);
        rows.put(new JSONObject().put("id",id).put("tag",parsed.tag).put("events",parsed.count())
            .put("sha256",MainActivity.sha(source)).put("bytes",source.length));
        MainActivity.write(new File(dir,"index.json"),rows.toString().getBytes(StandardCharsets.UTF_8));
    }
    static synchronized byte[] next(File files)throws Exception{
        JSONArray rows=rows(files);if(rows.length()==0)throw new IOException("队列为空");
        JSONObject first=rows.getJSONObject(0);String id=first.getString("id");
        if(!id.matches("[a-f0-9-]{36}"))throw new IOException("队列标识无效");
        byte[] source=MainActivity.read(new FileInputStream(new File(directory(files),id+".html")),ReplaySource.MAX_BYTES);
        if(!MainActivity.sha(source).equals(first.getString("sha256")))throw new IOException("队列文件校验不符");
        MainActivity.checkedSource(source);return source;
    }
    static synchronized String diagnostic(File files)throws Exception{
        JSONArray rows=rows(files);if(rows.length()==0)return "";
        JSONObject first=rows.getJSONObject(0);
        if(!first.optBoolean("diagnostic_only",false))return "";
        String id=first.getString("id");
        if(!id.matches("[a-f0-9-]{36}"))throw new IOException("诊断队列标识无效");
        File evidence=new File(directory(files),id+".diagnostic.json");
        byte[] raw=MainActivity.read(new FileInputStream(evidence),4*1024*1024);
        if(!MainActivity.sha(raw).equals(first.optString("diagnostic_sha256","")))throw new IOException("诊断证据校验不符");
        JSONObject proof=new JSONObject(new String(raw,StandardCharsets.UTF_8));
        if(!proof.optBoolean("user_authorized",false)||!proof.optString("source_sha256","").equals(first.getString("sha256")))throw new IOException("诊断授权与原HTML不符");
        return evidence.getAbsolutePath();
    }
    static synchronized void consume(File files,String hash)throws Exception{
        JSONArray rows=rows(files);if(rows.length()==0||!rows.getJSONObject(0).getString("sha256").equals(hash))throw new IOException("队列已改变");
        JSONArray rest=new JSONArray();for(int i=1;i<rows.length();i++)rest.put(rows.getJSONObject(i));
        MainActivity.write(new File(directory(files),"index.json"),rest.toString().getBytes(StandardCharsets.UTF_8));
        // Original HTML remains available for diagnostics; never delete game data.
    }
}
