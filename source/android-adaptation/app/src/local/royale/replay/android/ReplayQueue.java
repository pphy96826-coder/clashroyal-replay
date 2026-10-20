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
    /** Picker result to queue; shared by the console and the floating window. */
    static int importFrom(android.content.Context context,android.content.Intent data)throws Exception{
        java.util.ArrayList<android.net.Uri> uris=new java.util.ArrayList<android.net.Uri>();
        // Reflection keeps the compile-only compatibility API independent
        // of ClipData stubs; actual calls use the platform's public API.
        Object clip=android.content.Intent.class.getMethod("getClipData").invoke(data);
        if(clip!=null){int count=((Integer)clip.getClass().getMethod("getItemCount").invoke(clip)).intValue();
            if(count>128)throw new IOException("一次最多导入128场");
            for(int i=0;i<count;i++){Object item=clip.getClass().getMethod("getItemAt",int.class).invoke(clip,i);uris.add((android.net.Uri)item.getClass().getMethod("getUri").invoke(item));}
        }else if(data.getData()!=null)uris.add(data.getData());
        int added=0;
        try{
            for(android.net.Uri uri:uris){
                if(!"content".equals(uri.getScheme()))throw new IOException("仅接受文件选择器授权的HTML");
                InputStream in=context.getContentResolver().openInputStream(uri);if(in==null)throw new IOException("文件不可读");
                byte[] source=MainActivity.read(in,ReplaySource.MAX_BYTES);ReplaySource.Info parsed=MainActivity.checkedSource(source);
                add(context.getFilesDir(),source,parsed);added++;
            }
        }catch(Exception e){throw new IOException("已加入队列 "+added+" 场；"+e.getMessage());}
        return added;
    }
    private static int find(JSONArray rows,String id)throws Exception{
        if(!id.matches("[a-f0-9-]{36}"))throw new IOException("队列标识无效");
        for(int i=0;i<rows.length();i++)if(id.equals(rows.getJSONObject(i).optString("id","")))return i;
        throw new IOException("该场已不在队列中");
    }
    /** Only queued copies that never started are removed; task records stay. */
    static synchronized void remove(File files,String id)throws Exception{
        JSONArray rows=rows(files);int index=find(rows,id);JSONArray rest=new JSONArray();
        for(int i=0;i<rows.length();i++)if(i!=index)rest.put(rows.getJSONObject(i));
        File dir=directory(files);
        MainActivity.write(new File(dir,"index.json"),rest.toString().getBytes(StandardCharsets.UTF_8));
        new File(dir,id+".html").delete();new File(dir,id+".diagnostic.json").delete();
    }
    static synchronized void moveToFront(File files,String id)throws Exception{
        JSONArray rows=rows(files);int index=find(rows,id);if(index==0)return;
        JSONArray order=new JSONArray();order.put(rows.getJSONObject(index));
        for(int i=0;i<rows.length();i++)if(i!=index)order.put(rows.getJSONObject(i));
        MainActivity.write(new File(directory(files),"index.json"),order.toString().getBytes(StandardCharsets.UTF_8));
    }
    static synchronized int clear(File files)throws Exception{
        JSONArray rows=rows(files);File dir=directory(files);
        MainActivity.write(new File(dir,"index.json"),"[]".getBytes(StandardCharsets.UTF_8));
        for(int i=0;i<rows.length();i++){String id=rows.getJSONObject(i).optString("id","");
            if(id.matches("[a-f0-9-]{36}")){new File(dir,id+".html").delete();new File(dir,id+".diagnostic.json").delete();}}
        return rows.length();
    }
    static synchronized void consume(File files,String hash)throws Exception{
        JSONArray rows=rows(files);if(rows.length()==0||!rows.getJSONObject(0).getString("sha256").equals(hash))throw new IOException("队列已改变");
        JSONArray rest=new JSONArray();for(int i=1;i<rows.length();i++)rest.put(rows.getJSONObject(i));
        MainActivity.write(new File(directory(files),"index.json"),rest.toString().getBytes(StandardCharsets.UTF_8));
        // Original HTML remains available for diagnostics; never delete game data.
    }
}
