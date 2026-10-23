package local.royale.replay.android;

import android.content.Context;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.json.JSONObject;

/** Bounded, pure HTML work; independent of the game's native operation lease. */
final class SourcePreparation {
    private static final Object[] locks=new Object[32];
    static{for(int i=0;i<locks.length;i++)locks[i]=new Object();}
    private static final Set<String> pending=new HashSet<String>();
    private static final Map<String,String> stages=new HashMap<String,String>();
    private static int workers;
    private static File cache(Context context,String hash)throws Exception{
        File dir=new File(context.getFilesDir(),"source-cache");if(!dir.isDirectory()&&!dir.mkdir())throw new IOException("cannot create source cache");
        return new File(dir,NativePython.sourceRuntime(context).getName()+"-"+hash+".json");
    }
    static JSONObject checked(File files,JSONObject record,byte[] source)throws Exception{
        String hash=MainActivity.sha(source);
        File manifest=new File(record.getString("private_source_manifest")).getCanonicalFile();
        File imports=new File(files,"local-imports").getCanonicalFile();
        if(!manifest.getPath().startsWith(imports.getPath()+File.separator)||!manifest.getName().equals("source.json")||!manifest.getParentFile().getName().equals("result"))throw new IOException("source cache leaves private imports");
        byte[] raw=MainActivity.read(new FileInputStream(manifest),32*1024*1024);
        if(!MainActivity.sha(raw).equals(record.getString("manifest_sha256")))throw new IOException("cached source changed");
        byte[] original=MainActivity.read(new FileInputStream(new File(manifest.getParentFile().getParentFile(),"input.html")),ReplaySource.MAX_BYTES);
        JSONObject doc=new JSONObject(new String(raw,StandardCharsets.UTF_8));
        if(!hash.equals(MainActivity.sha(original))||!hash.equals(record.optString("source_sha256",""))||!hash.equals(doc.optString("source_sha256",""))
            ||record.optBoolean("desktop_backend_used",true)||record.optBoolean("native_calls",true)
            ||!record.optString("schema","").equals("royale-replay.android-full-import.v1")
            ||doc.optInt("retained_action_count",-1)!=record.optInt("retained_events",-2))throw new IOException("cached source identity differs");
        return new JSONObject(record.toString());
    }
    static JSONObject prepare(Context context,byte[] source)throws Exception{
        String hash=MainActivity.sha(source);File index=cache(context,hash);
        synchronized(locks[(hash.hashCode()&0x7fffffff)%locks.length]){
            if(index.isFile())try{return checked(context.getFilesDir(),new JSONObject(MainActivity.text(index,32768)),source);}catch(Exception stale){/* Pure cache miss; never a native result. */}
            JSONObject report=NativePython.parseUncached(context,source);
            report.put("manifest_sha256",MainActivity.sha(MainActivity.read(new FileInputStream(report.getString("private_source_manifest")),32*1024*1024)));
            checked(context.getFilesDir(),report,source);
            MainActivity.write(index,report.toString().getBytes(StandardCharsets.UTF_8));return report;
        }
    }
    static synchronized String stage(String id){return stages.containsKey(id)?stages.get(id):"等待解析";}
    static void schedule(final Context supplied){
        if(ReplayReset.blocked(supplied))return;
        final Context context=supplied.getApplicationContext();
        synchronized(SourcePreparation.class){
            try{org.json.JSONArray rows=ReplayQueue.rows(context.getFilesDir());for(int i=0;i<rows.length();i++){String id=rows.getJSONObject(i).getString("id");if(!stages.containsKey(id))pending.add(id);}}catch(Exception ignored){return;}
            // At most two small native parser processes. Stay at one when Android
            // reports memory pressure; never run another game/native simulator.
            int limit=1;
            try{android.app.ActivityManager.MemoryInfo memory=new android.app.ActivityManager.MemoryInfo();((android.app.ActivityManager)context.getSystemService(Context.ACTIVITY_SERVICE)).getMemoryInfo(memory);if(!memory.lowMemory&&memory.availMem>768L*1024*1024)limit=2;}catch(Exception ignored){}
            while(workers<limit&&!pending.isEmpty()){workers++;new Thread(new Runnable(){public void run(){drain(context);}},"replay-source-preparation").start();}
        }
    }
    private static void drain(Context context){
        try{for(;;){if(ReplayReset.blocked(context))return;String id;
            synchronized(SourcePreparation.class){if(pending.isEmpty())return;id=pending.iterator().next();pending.remove(id);stages.put(id,"解析中");}
            String result="来源已解析";
            try{prepare(context,ReplayQueue.source(context.getFilesDir(),id));}catch(Exception e){result="解析未通过";}
            synchronized(SourcePreparation.class){stages.put(id,result);}
            ConsoleActions.autoPrepare(context);
        }}finally{synchronized(SourcePreparation.class){workers--;}}
    }
}
