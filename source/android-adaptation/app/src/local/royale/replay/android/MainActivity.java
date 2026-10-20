package local.royale.replay.android;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.widget.*;
import android.view.View;
import java.io.*;
import java.nio.charset.*;
import java.security.MessageDigest;
import java.util.*;
import org.json.JSONObject;

/** Everyday UI only. Diagnostic instrumentations remain available separately. */
public final class MainActivity extends Activity {
    private final Handler handler=new Handler();
    private TextView status,details,sourceLabel,queueLabel;
    private Button choose,speedButton,watch,stop,replay,exitReplay,removeReplay;
    private int speedIndex=2;
    private final double[] speeds={.25,.5,1,2,4};
    private volatile boolean importing;
    private volatile boolean queueImporting;
    private Button nextQueue;
    private boolean closed;
    private volatile boolean finishing,reconciling;
    private long nextReconcile;
    private String uiNote="";
    private volatile String reconciliationNote="";
    private PlaybackHandoff handoff;
    private final Runnable refresh=new Runnable(){public void run(){if(!closed){updateStatus();handler.postDelayed(this,1000);}}};

    @Override public void onCreate(Bundle state){
        super.onCreate(state);setTitle("安卓回放控制台");
        handoff=new PlaybackHandoff(this);
        LinearLayout root=new LinearLayout(this);root.setOrientation(1);root.setPadding(26,30,26,24);root.setBackgroundColor(0xff101b2e);
        ScrollView scroll=new ScrollView(this);scroll.setBackgroundColor(0xff101b2e);scroll.addView(root);setContentView(scroll);
        label(root,"官服战斗回放",25,0xfff0f5ff);
        status=label(root,"就绪 · 选择回放即可播放",21,0xff80e8d5);
        details=label(root,"准备、加载和实际播放分别显示。切到游戏后，下拉通知栏仍可查看状态。",15,0xffb4c4da);
        sourceLabel=label(root,"",14,0xffb4c4da);
        button(root,"打开 RoyaleAPI 网页",new View.OnClickListener(){public void onClick(View v){startActivity(new Intent(MainActivity.this,BrowserActivity.class).putExtra("speed",speeds[speedIndex]));}});
        choose=button(root,"选择 HTML 并播放",new View.OnClickListener(){public void onClick(View v){pick();}});
        button(root,"添加多个 HTML 到队列",new View.OnClickListener(){public void onClick(View v){pickQueue();}});
        queueLabel=label(root,"队列为空",14,0xffb4c4da);
        nextQueue=button(root,"播放下一个",new View.OnClickListener(){public void onClick(View v){playNext();}});
        speedButton=button(root,"播放倍速：1×",new View.OnClickListener(){public void onClick(View v){speedIndex=(speedIndex+1)%speeds.length;speedButton.setText("播放倍速："+speeds[speedIndex]+"×");}});
        watch=button(root,"返回游戏观看",new View.OnClickListener(){public void onClick(View v){try{PlaybackService.openGame(MainActivity.this);}catch(Exception e){status.setText(e.getMessage());}}});
        stop=button(root,"停止当前回放",new View.OnClickListener(){public void onClick(View v){confirmStop();}});
        replay=button(root,"重放本场",new View.OnClickListener(){public void onClick(View v){finishReplay(true);}});
        exitReplay=button(root,"退出回放",new View.OnClickListener(){public void onClick(View v){finishReplay(false);}});
        removeReplay=button(root,"移除已保存回放",new View.OnClickListener(){public void onClick(View v){confirmRemove();}});
        label(root,"本机独立播放 · 无需电脑\n校验后用悬浮进度卡陪同加载，确认开播后收起。网页仅内置浏览器直连，不改电脑或系统网络。",13,0xff9aaec8);
        try{JSONObject meta=new JSONObject(text(new File(getFilesDir(),"source.json"),8192));sourceLabel.setText("上次导入："+meta.optString("tag","")+" · "+meta.optLong("events",0)+" 条指令");}catch(Exception ignored){}
        handler.post(refresh);
    }
    private TextView label(LinearLayout root,String value,int size,int color){TextView text=new TextView(this);text.setText(value);text.setTextSize(size);text.setTextColor(color);text.setPadding(0,12,0,16);root.addView(text);return text;}
    private Button button(LinearLayout root,String value,View.OnClickListener listener){Button b=new Button(this);b.setText(value);b.setOnClickListener(listener);root.addView(b);return b;}
    private void pick(){if(!OverlayAccess.ensure(this)){uiNote="请在系统页面允许悬浮进度卡，返回后重新选择 HTML。";return;}Intent intent=new Intent("android.intent.action.OPEN_DOCUMENT");intent.addCategory("android.intent.category.OPENABLE");intent.setType("*/*");intent.addFlags(1);startActivityForResult(intent,41);}
    @Override protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);
        if(request==42&&result==RESULT_OK&&data!=null){importQueue(data);return;}
        if(request==41&&result==RESULT_OK&&data!=null&&data.getData()!=null)importUri(data.getData());}
    private void pickQueue(){
        if(queueImporting)return;
        Intent intent=new Intent("android.intent.action.OPEN_DOCUMENT");intent.addCategory("android.intent.category.OPENABLE");
        intent.setType("*/*");intent.addFlags(1);intent.putExtra("android.intent.extra.ALLOW_MULTIPLE",true);startActivityForResult(intent,42);
    }
    private void importQueue(final Intent data){
        if(queueImporting)return;queueImporting=true;
        new Thread(new Runnable(){public void run(){int added=0;String error="";try{
            ArrayList<Uri> uris=new ArrayList<Uri>();
            // Reflection keeps the compile-only compatibility API independent
            // of ClipData stubs; actual calls use the platform's public API.
            Object clip=Intent.class.getMethod("getClipData").invoke(data);
            if(clip!=null){int count=((Integer)clip.getClass().getMethod("getItemCount").invoke(clip)).intValue();
                if(count>128)throw new IOException("一次最多导入128场");
                for(int i=0;i<count;i++){Object item=clip.getClass().getMethod("getItemAt",int.class).invoke(clip,i);uris.add((Uri)item.getClass().getMethod("getUri").invoke(item));}
            }else if(data.getData()!=null)uris.add(data.getData());
            for(Uri uri:uris){
                if(!"content".equals(uri.getScheme()))throw new IOException("仅接受文件选择器授权的HTML");
                InputStream in=getContentResolver().openInputStream(uri);if(in==null)throw new IOException("文件不可读");
                byte[] source=read(in,ReplaySource.MAX_BYTES);ReplaySource.Info parsed=checkedSource(source);
                ReplayQueue.add(getFilesDir(),source,parsed);added++;
            }
        }catch(Exception e){error=e.getMessage();}finally{
            final String message="已加入队列 "+added+" 场"+(error.isEmpty()?"":"；"+error);
            runOnUiThread(new Runnable(){public void run(){queueImporting=false;uiNote=message;updateStatus();}});
        }}}).start();
    }
    private void playNext(){
        if(finishing||PlaybackService.isBusy())return;
        if(!OverlayAccess.ensure(this))return;
        finishing=true;
        new Thread(new Runnable(){public void run(){try{
            JSONObject state=PlaybackStatus.read(MainActivity.this);
            byte[] source=ReplayQueue.next(getFilesDir());
            if(state.optString("state","").equals("complete")){NativePython.finishCompleted(MainActivity.this,state);PlaybackService.openGame(MainActivity.this);}
            else if(PlaybackStatus.ownsTask(state))throw new IOException("当前任务尚未完成，不覆盖战斗");
            ReplaySource.Info parsed=checkedSource(source);saveSource(MainActivity.this,source,parsed);
            PlaybackService.begin(MainActivity.this,source,speeds[speedIndex],true,ReplayQueue.diagnostic(getFilesDir()));
            ReplayQueue.consume(getFilesDir(),sha(source));
            uiNote="已请求队列下一场；先完成场景校验，不重复提交原生任务。";
        }catch(Exception e){uiNote="下一场未开始："+e.getMessage();}finally{finishing=false;}}}).start();
    }
    private void importUri(final Uri uri){
        if(!"content".equals(uri.getScheme())){status.setText("仅接受系统文件选择器授予的文件。");return;}
        if(importing)return;uiNote="";importing=true;choose.setEnabled(false);status.setText("正在读取所选 HTML…");
        final double speed=speeds[speedIndex];
        new Thread(new Runnable(){public void run(){try{
            InputStream in=getContentResolver().openInputStream(uri);if(in==null)throw new IOException("文件不可读");
            final byte[] bytes=read(in,ReplaySource.MAX_BYTES);
            final ReplaySource.Info parsed=checkedSource(bytes);
            saveSource(MainActivity.this,bytes,parsed);
            runOnUiThread(new Runnable(){public void run(){try{
                sourceLabel.setText("回放 "+parsed.tag+" · "+parsed.count()+" 条指令");
                boolean started=PlaybackService.submitOrQueue(MainActivity.this,bytes,speed);
                if(!started)uiNote="本场已加入待播队列，尚未播放；当前回放保持不变。";
            }catch(Exception e){uiNote="未开始播放："+e.getMessage();status.setText(uiNote);}finally{importing=false;choose.setEnabled(true);}}});
        }catch(final Exception e){runOnUiThread(new Runnable(){public void run(){importing=false;choose.setEnabled(true);uiNote="导入失败："+e.getMessage()+"；未播放上次文件。";status.setText(uiNote);}});}}}).start();
    }
    static ReplaySource.Info checkedSource(byte[] bytes)throws Exception{
        if(bytes.length>ReplaySource.MAX_BYTES)throw new IOException("HTML 超过大小上限");
        return ReplaySource.parse(StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).decode(java.nio.ByteBuffer.wrap(bytes)).toString());
    }
    static void saveSource(android.content.Context context,byte[] bytes,ReplaySource.Info parsed)throws Exception{
        SavedReplay.save(context.getFilesDir(),bytes,parsed);
    }
    private void updateStatus(){
        try{
            JSONObject state=PlaybackStatus.read(this);
            if(!PlaybackStatus.ownsTask(state))reconciliationNote="";
            if(!importing){status.setText(PlaybackStatus.title(state));details.setText(PlaybackStatus.detail(state,System.currentTimeMillis()/1000)+(uiNote.isEmpty()?"":"\n"+uiNote)+(reconciliationNote.isEmpty()?"":"\n"+reconciliationNote));}
            boolean active=PlaybackStatus.ownsTask(state);
            boolean complete=state.optString("state","").equals("complete");
            org.json.JSONArray queued=ReplayQueue.rows(getFilesDir());
            queueLabel.setText("队列待播："+queued.length()+" 场"+(queued.length()>0?" · 下一场 "+queued.getJSONObject(0).optString("tag","")+(queued.getJSONObject(0).optBoolean("diagnostic_only",false)?"（未完成诊断预览）":""):"")+(queueImporting?" · 后台解析中":""));
            nextQueue.setEnabled(queued.length()>0&&!importing&&!finishing&&!PlaybackService.isBusy()&&(complete||!active));
            JSONObject saved=SavedReplay.metadata(getFilesDir());
            sourceLabel.setText(saved==null?"尚未选择回放":"已保存回放："+saved.optString("tag","")+" · "+saved.optLong("events",0)+" 条指令"
                +(active?"\n当前任务："+(saved.optString("sha256","").equals(state.optString("source_sha256",""))?"与已保存回放相同":"另一份 HTML；不会被新文件覆盖"):""));
            watch.setVisibility(active?View.VISIBLE:View.GONE);
            stop.setVisibility(PlaybackStatus.canStop(state,System.currentTimeMillis()/1000)?View.VISIBLE:View.GONE);
            replay.setText(complete?"重放本场":"重放已保存回放");
            replay.setVisibility((complete||saved!=null)?View.VISIBLE:View.GONE);exitReplay.setVisibility(complete?View.VISIBLE:View.GONE);
            replay.setEnabled(!importing&&!finishing&&!PlaybackService.isBusy()&&(complete||!active));exitReplay.setEnabled(!finishing&&!PlaybackService.isBusy());
            removeReplay.setVisibility(saved!=null?View.VISIBLE:View.GONE);removeReplay.setEnabled(!importing&&!finishing&&!PlaybackService.isBusy());
            choose.setEnabled(!importing&&!finishing&&!PlaybackService.isBusy());
            speedButton.setEnabled(!finishing&&!PlaybackService.isBusy());
            reconcile(state);
            handoff.check();
        }catch(Exception e){if(!importing)status.setText("状态暂不可读；不会自动重试回放。");}
    }
    private void reconcile(final JSONObject state){
        if(importing||finishing||reconciling||PlaybackService.isBusy()||!PlaybackStatus.ownsTask(state)||System.currentTimeMillis()<nextReconcile)return;
        nextReconcile=System.currentTimeMillis()+5000;reconciling=true;
        new Thread(new Runnable(){public void run(){try{NativePython.reconcileReleased(MainActivity.this,state);reconciliationNote="";}catch(Exception error){reconciliationNote="旧任务核验失败："+error.getMessage()+"；现场保留，未重复提交。";}finally{reconciling=false;}}}).start();
    }
    private void finishReplay(final boolean again){
        if(finishing||PlaybackService.isBusy())return;
        finishing=true;uiNote=again?"正在安全释放本场回放，随后重新播放…":"正在安全退出回放…";
        new Thread(new Runnable(){public void run(){try{
            final JSONObject state=PlaybackStatus.read(MainActivity.this);
            boolean complete=state.optString("state","").equals("complete");
            final byte[] source;
            if(complete){
                File directory=PlaybackStatus.activeDirectory(MainActivity.this);
                source=again?read(new FileInputStream(new File(directory.getParentFile().getParentFile(),"input.html")),ReplaySource.MAX_BYTES):null;
                if(again&&!sha(source).equals(state.optString("source_sha256","")))throw new IOException("本场原始 HTML 校验不符，未使用其他文件重放");
                NativePython.finishCompleted(MainActivity.this,state);
                if(again)PlaybackService.openGame(MainActivity.this);
            }else{
                if(!again||PlaybackStatus.ownsTask(state))throw new IOException("旧任务仍需安全核验，未覆盖游戏现场");
                JSONObject saved=SavedReplay.metadata(getFilesDir());
                if(saved==null)throw new IOException("没有已保存回放");
                source=SavedReplay.load(getFilesDir(),saved.getString("sha256"));
            }
            runOnUiThread(new Runnable(){public void run(){try{
                uiNote="";
                if(again){PlaybackService.begin(MainActivity.this,source,speeds[speedIndex],true);}
            }catch(Exception e){uiNote="未开始重放："+e.getMessage();}finally{finishing=false;updateStatus();}}});
        }catch(final Exception e){runOnUiThread(new Runnable(){public void run(){finishing=false;uiNote="未操作回放："+e.getMessage();updateStatus();}});}}}).start();
    }
    private void confirmRemove(){
        try{
            final JSONObject saved=SavedReplay.metadata(getFilesDir());if(saved==null)return;
            new AlertDialog.Builder(this).setTitle("移除已保存回放？")
                .setMessage("仅从控制台入口移除，不停止游戏、不删除原始 HTML 或诊断记录。重新选择文件即可恢复。")
                .setNegativeButton("取消",null).setPositiveButton("移除",new DialogInterface.OnClickListener(){public void onClick(DialogInterface dialog,int which){try{
                    SavedReplay.hide(getFilesDir(),saved.getString("sha256"));uiNote="已移除保存入口；原始文件和诊断记录保留。";updateStatus();
                }catch(Exception e){uiNote=e.getMessage();}}}).show();
        }catch(Exception e){uiNote=e.getMessage();}
    }
    private void confirmStop(){
        new AlertDialog.Builder(this).setTitle("停止本机回放？")
            .setMessage("将先核对当前场景归属，再仅重启游戏客户端。不会重启模拟器或修改网络。")
            .setNegativeButton("取消",null).setPositiveButton("停止回放",new DialogInterface.OnClickListener(){public void onClick(DialogInterface dialog,int which){try{
                JSONObject state=PlaybackStatus.read(MainActivity.this);
                if(!PlaybackStatus.canStop(state,System.currentTimeMillis()/1000))throw new IOException("观察已结束或状态过期；未执行重启，请先检查游戏现场");
                File directory=PlaybackStatus.activeDirectory(MainActivity.this);
                write(new File(directory,"stop-request.json"),new JSONObject().put("user_requested_client_only_restart",true).toString().getBytes(StandardCharsets.UTF_8));
                uiNote="已请求停止 · 等待安全边界确认";status.setText(uiNote);
            }catch(Exception e){uiNote="未停止："+e.getMessage();status.setText(uiNote);}}}).show();
    }
    static byte[] read(InputStream in,int limit)throws IOException{try{ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] buf=new byte[16384];int n;while((n=in.read(buf))!=-1){if(out.size()+n>limit)throw new IOException("文件超过大小上限");out.write(buf,0,n);}return out.toByteArray();}finally{in.close();}}
    static String text(File f,int limit)throws IOException{return new String(read(new FileInputStream(f),limit),StandardCharsets.UTF_8);}
    static void write(File file,byte[] bytes)throws IOException{File temp=new File(file.getParentFile(),file.getName()+".tmp");FileOutputStream out=new FileOutputStream(temp);try{out.write(bytes);out.getFD().sync();}finally{out.close();}if(!temp.renameTo(file))throw new IOException("原子保存失败");}
    static String sha(byte[] bytes){try{StringBuilder out=new StringBuilder();for(byte v:MessageDigest.getInstance("SHA-256").digest(bytes))out.append(String.format(Locale.ROOT,"%02x",v&255));return out.toString();}catch(Exception e){throw new IllegalStateException(e);}}
    @Override protected void onResume(){super.onResume();PlaybackService.consoleVisible();if(handoff!=null)handoff.resume();}
    @Override protected void onPause(){if(handoff!=null)handoff.pause();super.onPause();}
    @Override protected void onDestroy(){closed=true;handler.removeCallbacks(refresh);super.onDestroy();}
}
