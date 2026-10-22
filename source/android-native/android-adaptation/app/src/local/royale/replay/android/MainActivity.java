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
    private Button choose,speedButton,watch,stop,replay,exitReplay,removeReplay,exportDiagnostic,floating;
    private LinearLayout queueRows;
    private String queueShown;
    private volatile boolean exportingDiagnostic;
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
        button(root,"打开 RoyaleAPI 网页",new View.OnClickListener(){public void onClick(View v){startActivity(new Intent(MainActivity.this,BrowserActivity.class).putExtra("speed",ConsoleActions.speed()));}});
        choose=button(root,"选择 HTML 并播放",new View.OnClickListener(){public void onClick(View v){pick();}});
        button(root,"添加多个 HTML 到队列",new View.OnClickListener(){public void onClick(View v){pickQueue();}});
        queueLabel=label(root,"队列为空",14,0xffb4c4da);
        queueRows=new LinearLayout(this);queueRows.setOrientation(1);root.addView(queueRows);
        nextQueue=button(root,"播放下一个",new View.OnClickListener(){public void onClick(View v){playNext();}});
        speedButton=button(root,ConsoleActions.speedLabel(),new View.OnClickListener(){public void onClick(View v){ConsoleActions.cycleSpeed();speedButton.setText(ConsoleActions.speedLabel());}});
        watch=button(root,"返回游戏观看",new View.OnClickListener(){public void onClick(View v){try{PlaybackService.openGame(MainActivity.this);}catch(Exception e){status.setText(e.getMessage());}}});
        stop=button(root,"停止当前回放",new View.OnClickListener(){public void onClick(View v){confirmStop();}});
        replay=button(root,"重放本场",new View.OnClickListener(){public void onClick(View v){finishReplay(true);}});
        exitReplay=button(root,"退出回放",new View.OnClickListener(){public void onClick(View v){finishReplay(false);}});
        removeReplay=button(root,"移除已保存回放",new View.OnClickListener(){public void onClick(View v){confirmRemove();}});
        floating=button(root,"开启游戏内悬浮控制台",new View.OnClickListener(){public void onClick(View v){toggleFloating();}});
        exportDiagnostic=button(root,"导出诊断",new View.OnClickListener(){public void onClick(View v){pickDiagnosticDestination();}});
        seedStop=button(root,"停止匹配，用当前最接近的开播",new View.OnClickListener(){public void onClick(View v){
            new Thread(new Runnable(){public void run(){String note;try{note=ConsoleActions.stopSeedSearch(MainActivity.this);}catch(Exception e){note="未停止："+e.getMessage();}
                final String result=note;runOnUiThread(new Runnable(){public void run(){uiNote=result;updateStatus();}});}}).start();}});
        resetAll=button(root,"重置所有回放进程（卡住时用）",new View.OnClickListener(){public void onClick(View v){confirmReset();}});
        cleanButton=button(root,"清理旧运行环境和任务记录",new View.OnClickListener(){public void onClick(View v){confirmClean();}});
        button(root,"冻结卡顿的指纹服务（虚拟机卡顿时用）",new View.OnClickListener(){public void onClick(View v){
            uiNote="正在检查指纹服务占用…";updateStatus();
            new Thread(new Runnable(){public void run(){String note;try{note=ConsoleActions.stopBusyFingerprint();}catch(Exception e){note="未停止："+e.getMessage();}
                final String result=note;runOnUiThread(new Runnable(){public void run(){uiNote=result;updateStatus();}});}}).start();}});
        label(root,"本机独立播放 · 无需电脑\n校验后用悬浮进度卡陪同加载，确认开播后收起。网页仅内置浏览器直连，不改电脑或系统网络。",13,0xff9aaec8);
        try{JSONObject meta=new JSONObject(text(new File(getFilesDir(),"source.json"),8192));sourceLabel.setText("上次导入："+meta.optString("tag","")+" · "+meta.optLong("events",0)+" 条指令");}catch(Exception ignored){}
        handler.post(refresh);
    }
    private TextView label(LinearLayout root,String value,int size,int color){TextView text=new TextView(this);text.setText(value);text.setTextSize(size);text.setTextColor(color);text.setPadding(0,12,0,16);root.addView(text);return text;}
    private Button button(LinearLayout root,String value,View.OnClickListener listener){Button b=new Button(this);b.setText(value);b.setOnClickListener(listener);root.addView(b);return b;}
    private void pick(){if(!OverlayAccess.ensure(this)){uiNote="请在系统页面允许悬浮进度卡，返回后重新选择 HTML。";return;}Intent intent=new Intent("android.intent.action.OPEN_DOCUMENT");intent.addCategory("android.intent.category.OPENABLE");intent.setType("*/*");intent.addFlags(1);startActivityForResult(intent,41);}
    @Override protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);
        if(request==43){if(result==RESULT_OK&&data!=null&&data.getData()!=null)exportDiagnostic(data.getData());else{uiNote="已取消导出诊断；原始记录未改变。";updateStatus();}return;}
        if(request==42&&result==RESULT_OK&&data!=null){importQueue(data);return;}
        if(request==41&&result==RESULT_OK&&data!=null&&data.getData()!=null)importUri(data.getData());}
    private void pickDiagnosticDestination(){
        if(exportingDiagnostic)return;
        new AlertDialog.Builder(this).setTitle("导出当前任务诊断？")
            .setMessage("仅导出本控制台的错误、牌序与组件记录，不包含原始 HTML、游戏 APK 或浏览器 Cookie。记录含本机路径和进程信息，请只私下发送。不会清理、停止或重新播放游戏。建议保存在本机 Download 文件夹。")
            .setNegativeButton("取消",null).setPositiveButton("选择保存位置",new DialogInterface.OnClickListener(){public void onClick(DialogInterface dialog,int which){try{
                Intent intent=new Intent("android.intent.action.CREATE_DOCUMENT");intent.addCategory("android.intent.category.OPENABLE");
                intent.setType("application/zip").putExtra("android.intent.extra.TITLE","回放诊断-"+System.currentTimeMillis()+".zip").addFlags(2);
                startActivityForResult(intent,43);
            }catch(Exception error){uiNote="无法打开保存窗口："+error.getMessage();updateStatus();}}}).show();
    }
    private void exportDiagnostic(final Uri uri){
        if(exportingDiagnostic)return;
        if(!"content".equals(uri.getScheme())){uiNote="导出失败：仅接受系统保存窗口授权的位置。";updateStatus();return;}
        exportingDiagnostic=true;exportDiagnostic.setEnabled(false);exportDiagnostic.setText("正在导出诊断…");
        new Thread(new Runnable(){public void run(){String message;try{
            File active=null;try{active=PlaybackStatus.taskDirectory(MainActivity.this,true);}catch(Exception ignored){}
            String environment="Android SDK: unknown; ABIs: unknown";
            try{environment="Android SDK: "+Class.forName("android.os.Build$VERSION").getField("SDK_INT").get(null)
                +"; ABIs: "+Arrays.toString((String[])Class.forName("android.os.Build").getField("SUPPORTED_ABIS").get(null));}catch(Exception ignored){}
            OutputStream stream=getContentResolver().openOutputStream(uri,"wt");if(stream==null)throw new IOException("保存位置不可写");
            int count;try(OutputStream output=stream){count=DiagnosticExport.write(getFilesDir(),active,output,environment);}
            message="诊断 ZIP 已保存（"+count+" 份记录）。请从所选文件夹私下发送；游戏现场未改变。";
        }catch(Exception error){message="导出未完成："+error.getMessage()+"。可能留下不完整 ZIP，请勿发送；原始记录未改变，可重新导出。";}
        final String note=message;runOnUiThread(new Runnable(){public void run(){exportingDiagnostic=false;if(closed)return;exportDiagnostic.setEnabled(true);exportDiagnostic.setText("导出诊断");uiNote=note;updateStatus();
            new AlertDialog.Builder(MainActivity.this).setTitle("诊断导出").setMessage(note).setPositiveButton("知道了",null).show();}});
        }}).start();
    }
    private void pickQueue(){
        if(queueImporting)return;
        Intent intent=new Intent("android.intent.action.OPEN_DOCUMENT");intent.addCategory("android.intent.category.OPENABLE");
        intent.setType("*/*");intent.addFlags(1);intent.putExtra("android.intent.extra.ALLOW_MULTIPLE",true);startActivityForResult(intent,42);
    }
    private void importQueue(final Intent data){
        if(queueImporting)return;queueImporting=true;
        new Thread(new Runnable(){public void run(){String message;try{
            message="已加入队列 "+ReplayQueue.importFrom(MainActivity.this,data)+" 场；会自动提前准备第一场。";
        }catch(Exception e){message=e.getMessage();}
            ConsoleActions.autoPrepare(MainActivity.this);
            final String note=message;
            runOnUiThread(new Runnable(){public void run(){queueImporting=false;uiNote=note;updateStatus();}});
        }}).start();
    }
    private void playNext(){
        if(finishing||(PlaybackService.isBusy()&&!PlaybackService.armedIdle()))return;
        if(!OverlayAccess.ensure(this))return;
        finishing=true;
        new Thread(new Runnable(){public void run(){try{
            uiNote=ConsoleActions.playNext(MainActivity.this);
        }catch(Exception e){uiNote="下一场未开始："+e.getMessage();}finally{finishing=false;}}}).start();
    }
    private void toggleFloating(){
        try{
            if(FloatingConsole.running()){FloatingConsole.setEnabled(this,false);FloatingConsole.shutdown(this);uiNote="已关闭游戏内悬浮控制台。";}
            else{FloatingConsole.setEnabled(this,true);if(!OverlayAccess.ensure(this)){uiNote="请在系统页面允许悬浮窗，返回后悬浮控制台会自动出现。";return;}
                FloatingConsole.start(this);uiNote="悬浮控制台已开启：切到游戏后点圆形“回放”按钮展开或收起，可拖动。";}
        }catch(Exception e){uiNote="悬浮控制台未切换："+e.getMessage();}
        updateStatus();
    }
    private void importUri(final Uri uri){
        if(!"content".equals(uri.getScheme())){status.setText("仅接受系统文件选择器授予的文件。");return;}
        if(importing)return;uiNote="";importing=true;choose.setEnabled(false);status.setText("正在读取所选 HTML…");
        final double speed=ConsoleActions.speed();
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
            String[] early=ConsoleActions.earlyStatus(state);
            if(!importing){status.setText(early!=null?early[0]:PlaybackStatus.title(state));details.setText((early!=null?early[1]:PlaybackStatus.detail(state,System.currentTimeMillis()/1000))+(uiNote.isEmpty()?"":"\n"+uiNote)+(reconciliationNote.isEmpty()?"":"\n"+reconciliationNote));}
            boolean active=PlaybackStatus.ownsTask(state);
            boolean complete=state.optString("state","").equals("complete");
            org.json.JSONArray queued=ReplayQueue.rows(getFilesDir());
            queueLabel.setText("队列待播："+queued.length()+" 场"+(queued.length()>0?" · 下一场 "+queued.getJSONObject(0).optString("tag","")+(queued.getJSONObject(0).optBoolean("diagnostic_only",false)?"（未完成诊断预览）":""):"")+(queueImporting?" · 后台解析中":""));
            nextQueue.setEnabled(queued.length()>0&&!importing&&!finishing&&ConsoleActions.canPlayNext(state));
            boolean editable=!finishing&&!ConsoleActions.starting();java.util.Map<String,String> statuses=ConsoleActions.rowStatus(this,queued);String shown=queued.toString()+editable+statuses;
            if(!shown.equals(queueShown)){queueShown=shown;QueueRows.render(this,queueRows,queued,statuses,false,editable,new QueueRows.Listener(){public void changed(String message){uiNote=message;queueShown=null;updateStatus();}});}
            speedButton.setText(ConsoleActions.speedLabel());
            floating.setText(FloatingConsole.running()?"关闭游戏内悬浮控制台":"开启游戏内悬浮控制台");
            JSONObject saved=SavedReplay.metadata(getFilesDir());
            sourceLabel.setText(saved==null?"尚未选择回放":"已保存回放："+saved.optString("tag","")+" · "+saved.optLong("events",0)+" 条指令"
                +(active?"\n当前任务："+(saved.optString("sha256","").equals(state.optString("source_sha256",""))?"与已保存回放相同":"另一份 HTML；不会被新文件覆盖"):""));
            watch.setVisibility(active?View.VISIBLE:View.GONE);
            stop.setVisibility(PlaybackStatus.canStop(state,System.currentTimeMillis()/1000)&&!PlaybackService.armedIdle()?View.VISIBLE:View.GONE);
            seedStop.setVisibility(ConsoleActions.seedSearching(state)?View.VISIBLE:View.GONE);
            replay.setText(complete?"重放本场":"重放已保存回放");
            replay.setVisibility((complete||saved!=null)?View.VISIBLE:View.GONE);exitReplay.setVisibility(complete?View.VISIBLE:View.GONE);
            replay.setEnabled(!importing&&!finishing&&(PlaybackService.armedIdle()||(!PlaybackService.isBusy()&&(complete||!active))));exitReplay.setEnabled(!finishing&&!PlaybackService.isBusy());
            removeReplay.setVisibility(saved!=null?View.VISIBLE:View.GONE);removeReplay.setEnabled(!importing&&!finishing&&!PlaybackService.isBusy());
            choose.setEnabled(!importing&&!finishing&&!PlaybackService.isBusy());
            speedButton.setEnabled(!finishing&&(!PlaybackService.isBusy()||PlaybackService.armedIdle()));
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
        if(finishing||(PlaybackService.isBusy()&&!(again&&PlaybackService.armedIdle())))return;
        finishing=true;uiNote=again?"正在安全释放本场回放，随后重新播放…":"正在安全退出回放…";
        new Thread(new Runnable(){public void run(){String note;
            try{ConsoleActions.finishReplay(MainActivity.this,again,false);note="";}catch(Exception e){note="未操作回放："+e.getMessage();}
            final String result=note;
            runOnUiThread(new Runnable(){public void run(){finishing=false;uiNote=result;updateStatus();}});
        }}).start();
    }
    private Button cleanButton;private long cleanArmedUntil;private volatile boolean cleaning;
    private void confirmClean(){
        if(cleaning)return;
        if(System.currentTimeMillis()>cleanArmedUntil){cleanArmedUntil=System.currentTimeMillis()+5000;cleanButton.setText("5 秒内再点一次：删除旧运行环境和过期任务记录");return;}
        cleanArmedUntil=0;cleaning=true;cleanButton.setEnabled(false);cleanButton.setText("正在清理…");
        new Thread(new Runnable(){public void run(){String note;
            try{note=ConsoleActions.cleanStorage(MainActivity.this);}catch(Exception e){note="未清理："+e.getMessage();}
            final String result=note;
            runOnUiThread(new Runnable(){public void run(){cleaning=false;cleanButton.setEnabled(true);cleanButton.setText("清理旧运行环境和任务记录");uiNote=result;updateStatus();}});
        }}).start();
    }
    private Button resetAll,seedStop;private long resetArmedUntil;private volatile boolean resetting;
    private void confirmReset(){
        if(resetting)return;
        if(System.currentTimeMillis()>resetArmedUntil){resetArmedUntil=System.currentTimeMillis()+5000;resetAll.setText("5 秒内再点一次：结束回放进程并关闭游戏");return;}
        resetArmedUntil=0;resetting=true;resetAll.setEnabled(false);resetAll.setText("正在重置…");
        new Thread(new Runnable(){public void run(){String note;
            try{note=ConsoleActions.resetAll(MainActivity.this);}catch(Exception e){note="重置未完成："+e.getMessage();}
            final String result=note;
            runOnUiThread(new Runnable(){public void run(){resetting=false;resetAll.setEnabled(true);resetAll.setText("重置所有回放进程（卡住时用）");uiNote=result;updateStatus();}});
        }}).start();
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
                ConsoleActions.requestStop(MainActivity.this);
                uiNote="已请求停止 · 等待安全边界确认";status.setText(uiNote);
            }catch(Exception e){uiNote="未停止："+e.getMessage();status.setText(uiNote);}}}).show();
    }
    static byte[] read(InputStream in,int limit)throws IOException{try{ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] buf=new byte[16384];int n;while((n=in.read(buf))!=-1){if(out.size()+n>limit)throw new IOException("文件超过大小上限");out.write(buf,0,n);}return out.toByteArray();}finally{in.close();}}
    static String text(File f,int limit)throws IOException{return new String(read(new FileInputStream(f),limit),StandardCharsets.UTF_8);}
    static void write(File file,byte[] bytes)throws IOException{File temp=new File(file.getParentFile(),file.getName()+".tmp");FileOutputStream out=new FileOutputStream(temp);try{out.write(bytes);out.getFD().sync();}finally{out.close();}if(!temp.renameTo(file))throw new IOException("原子保存失败");}
    static String sha(byte[] bytes){try{StringBuilder out=new StringBuilder();for(byte v:MessageDigest.getInstance("SHA-256").digest(bytes))out.append(String.format(Locale.ROOT,"%02x",v&255));return out.toString();}catch(Exception e){throw new IllegalStateException(e);}}
    @Override protected void onResume(){super.onResume();PlaybackService.consoleVisible();if(handoff!=null)handoff.resume();
        if(FloatingConsole.enabled(this)&&!FloatingConsole.running())try{FloatingConsole.start(this);}catch(Exception ignored){/* Console buttons still work. */}}
    @Override protected void onPause(){if(handoff!=null)handoff.pause();super.onPause();}
    @Override protected void onDestroy(){closed=true;handler.removeCallbacks(refresh);super.onDestroy();}
}
