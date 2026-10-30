package local.royale.replay.android;

import android.app.Activity;
import android.os.Bundle;
import java.io.*;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;

/** Explicit Mac/ADB job handoff. Export is guarded by system DUMP permission;
 * normal apps and browser links cannot invoke this unattended playback entry.
 * No URL fetch, shell strings, game APK changes or new root acquisition. */
public final class WebWorkerActivity extends Activity {
    static final String ACTION="local.royale.replay.android.WEB_REPLAY";
    /** Immutable per-request receipt; the global UI status can be reset or
     * superseded, so it must not be the Mac's only source of task ownership. */
    static void bindTask(android.content.Context context,String id,String request,String sha,JSONObject job)throws Exception{
        if(id.isEmpty())return;
        if(!id.matches("[a-f0-9-]{36}")||!request.matches("[a-f0-9-]{36}")||!sha.matches("[a-f0-9]{64}"))throw new IOException("无效网站任务绑定");
        if(!sha.equals(job.optString("source_sha256","")))throw new IOException("网站任务来源绑定不一致");
        File directory=PrivateTaskPaths.resolve(context.getFilesDir(),new File(job.getString("directory")),false);
        File receipt=new File(context.getFilesDir(),"web-jobs/"+id+".task.json");
        if(receipt.exists())throw new IOException("网站任务已有执行目录，未覆盖绑定");
        MainActivity.write(receipt,new JSONObject().put("job_id",id).put("request_id",request).put("source_sha256",sha)
            .put("directory",directory.getCanonicalPath()).put("updated_at",System.currentTimeMillis()/1000).toString().getBytes(StandardCharsets.UTF_8));
    }
    @Override public void onCreate(Bundle saved){
        super.onCreate(saved);
        if(saved!=null||!ACTION.equals(getIntent().getAction())){finish();return;}
        final String id=getIntent().getStringExtra("job_id"),sha=getIntent().getStringExtra("sha256"),tag=getIntent().getStringExtra("tag");
        if(id==null||!id.matches("[a-f0-9-]{36}")||sha==null||!sha.matches("[a-f0-9]{64}")||tag==null||!tag.matches("[A-Z0-9]{8,20}")){finish();return;}
        final File jobs=new File(getFilesDir(),"web-jobs");
        final File ledger=new File(jobs,id+".json");
        new Thread(new Runnable(){public void run(){boolean beginEntered=false;try{
            if(!jobs.isDirectory()&&!jobs.mkdir())throw new IOException("无法创建网站任务目录");
            // Persist BEFORE starting. Repeated or ambiguous handoffs never resubmit.
            if(!ledger.createNewFile())return;
            MainActivity.write(ledger,new JSONObject().put("job_id",id).put("state","reserved").put("source_sha256",sha).put("updated_at",System.currentTimeMillis()/1000).toString().getBytes(StandardCharsets.UTF_8));
            byte[] source=MainActivity.read(new FileInputStream(new File(getFilesDir(),"web-inbox/"+id+".html")),ReplaySource.MAX_BYTES);
            if(!MainActivity.sha(source).equals(sha))throw new IOException("网站 HTML 校验值不一致");
            ReplaySource.Info info=MainActivity.checkedSource(source);
            if(!tag.equals(info.tag))throw new IOException("HTML 对局编号与网站请求不一致");
            if(PlaybackService.isBusy())throw new IOException("模拟器已有任务；未覆盖现有回放");
            JSONObject previous=PlaybackStatus.read(WebWorkerActivity.this);
            if(previous.optString("state","").equals("complete")&&!previous.optBoolean("monitor_active",true))
                NativePython.reconcileReleased(WebWorkerActivity.this,previous);
            if(PlaybackStatus.ownsTask(PlaybackStatus.read(WebWorkerActivity.this)))throw new IOException("旧任务尚未释放，网站任务未覆盖或取消它");
            beginEntered=true;
            String request=PlaybackService.begin(WebWorkerActivity.this,source,1,true,"","",id);
            MainActivity.write(ledger,new JSONObject().put("job_id",id).put("state","accepted").put("request_id",request).put("source_sha256",sha).put("updated_at",System.currentTimeMillis()/1000).toString().getBytes(StandardCharsets.UTF_8));
        }catch(Exception e){try{
            MainActivity.write(ledger,new JSONObject().put("job_id",id).put("state","rejected").put("native_not_started",!beginEntered).put("source_sha256",sha).put("message",e.getMessage()).put("updated_at",System.currentTimeMillis()/1000).toString().getBytes(StandardCharsets.UTF_8));
        }catch(Exception ignored){/* Keep the reserved ledger; never retry. */}}finally{runOnUiThread(new Runnable(){public void run(){finish();}});}}}).start();
    }
}
