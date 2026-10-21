package local.royale.replay.android;

import android.app.Service;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.os.IBinder;
import android.os.Handler;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import org.json.JSONObject;

/** Visible, tappable progress. No boot receiver, sticky restart or native retry. */
public final class PlaybackService extends Service {
    private static volatile boolean busy;
    private volatile boolean running;
    private static volatile PlaybackService active;
    private final Handler ui=new Handler();
    private ReplayOverlay overlay;
    private boolean coverShown;
    static boolean isBusy(){return busy;}
    static boolean returnsToConsole(JSONObject state,boolean terminalVerified){
        String phase=state.optString("state","");
        return !state.optBoolean("monitor_active",true)
            &&((phase.equals("complete")&&terminalVerified)
                ||(phase.equals("released")&&state.optBoolean("generation_released",false)));
    }
    // Early preparation of a queue row: runs up to ready_to_open, then waits for
    // the user's play request. Nothing is published to the game before that.
    private static volatile String armedQueueId="",cancelQueueId="";
    private static volatile boolean armedPlaying;
    private static volatile double armedSpeed=1;
    static double armedSpeed(){return armedSpeed;}
    private static final java.util.Set<String> PRE_SCENE=new java.util.HashSet<String>(java.util.Arrays.asList("queued","preparing","calibrating","simulating","validating","waiting_preparation_lobby","ready_to_open"));
    /** Queue row prepared ahead and not yet asked to play; empty otherwise. */
    static String armedQueueId(){return armedPlaying?"":armedQueueId;}
    static boolean armedTask(){return busy&&!armedQueueId.isEmpty();}
    static boolean armedIdle(){return busy&&!armedQueueId.isEmpty()&&!armedPlaying;}
    /** Cancel only at the runtime's pre-scene boundary; ignored once playback was requested. */
    static void cancelArmed(String queueId){cancelQueueId=queueId;}
    static synchronized boolean submitOrQueue(Context context,byte[] source,double speed)throws Exception{
        ReplaySource.Info parsed=MainActivity.checkedSource(source);
        JSONObject state=PlaybackStatus.read(context);
        if(busy||PlaybackStatus.ownsTask(state)){
            String queued=ReplayQueue.add(context.getFilesDir(),source,parsed);
            ConsoleActions.imported(context);
            // An early-prepared row is not playing yet: the explicit choice replaces it.
            if(armedIdle()){ConsoleActions.moveQueuedToFront(context,queued);ConsoleActions.playNext(context);return true;}
            return false; // Only enqueued: never relabel another match as playing.
        }
        MainActivity.saveSource(context,source,parsed);
        begin(context,source,speed);return true;
    }
    static synchronized void begin(Context context,byte[] source,double speed)throws Exception{
        begin(context,source,speed,true);
    }
    static synchronized void begin(Context context,byte[] source,double speed,boolean replayRequested)throws Exception{
        begin(context,source,speed,replayRequested,"");
    }
    static synchronized void begin(Context context,byte[] source,double speed,boolean replayRequested,String diagnostic)throws Exception{
        begin(context,source,speed,replayRequested,diagnostic,"");
    }
    static synchronized void begin(Context context,byte[] source,double speed,boolean replayRequested,String diagnostic,String queueId)throws Exception{
        if(busy)throw new IOException("已有本机任务正在处理；不会重复播放");
        if(!OverlayAccess.allowed(context))throw new IOException("请先允许控制台显示悬浮进度卡，再重新选择 HTML");
        if(context.getPackageManager().getLaunchIntentForPackage(StandaloneDoctor.GAME)==null)throw new IOException("未找到已安装的指定客户端");
        MainActivity.checkedSource(source);
        File requests=new File(context.getFilesDir(),"phone-requests");
        if(!requests.isDirectory()&&!requests.mkdir())throw new IOException("无法创建私有请求目录");
        String id=UUID.randomUUID().toString();
        MainActivity.write(new File(requests,id+".html"),source);
        busy=true;armedQueueId=queueId;armedPlaying=false;cancelQueueId="";armedSpeed=speed;
        try{
            save(context,new JSONObject().put("state","queued").put("request_id",id).put("source_sha256",MainActivity.sha(source)).put("message","正在本机准备；整局校验后显示悬浮进度并打开游戏。"));
            context.startForegroundService(new Intent(context,PlaybackService.class).putExtra("request_id",id).putExtra("speed",speed).putExtra("replay_requested",replayRequested?"yes":"no").putExtra("diagnostic_prefix",diagnostic));
        }catch(Exception e){busy=false;armedQueueId="";save(context,new JSONObject().put("state","request_failed").put("message",e.toString()));throw e;}
    }
    static void openGame(Context context)throws IOException{
        Intent game=context.getPackageManager().getLaunchIntentForPackage(StandaloneDoctor.GAME);
        if(game==null)throw new IOException("未找到已安装的指定客户端");
        context.startActivity(game.addFlags(0x10000000));
    }
    /** User tap in the floating window, bound to the current service request. */
    static String playPrepared(Context context)throws Exception{
        PlaybackService service=active;if(service==null||!busy||!service.running)throw new IOException("当前没有待播放任务");
        JSONObject request=new JSONObject(MainActivity.text(new File(context.getFilesDir(),"phone-service-state.json"),32768));
        final File directory=PrivateTaskPaths.resolve(context.getFilesDir(),new File(request.getString("directory")),false);
        final String id=request.getString("request_id"),hash=request.getString("source_sha256");
        JSONObject state=new JSONObject(MainActivity.text(new File(directory,"status.json"),32768));
        if(!PlaybackHandoff.readyForForeground(state,hash,System.currentTimeMillis()/1000)||!NativePython.sameGameGeneration(state))throw new IOException("这一场尚未就绪或游戏已重新启动");
        service.ui.post(new Runnable(){public void run(){try{PlaybackHandoff.serviceForeground(service,id,hash,directory);}catch(Exception e){FloatingConsole.note(service,"未开播："+e.getMessage());}}});
        return "正在打开已就绪的本场回放。";
    }
    static void coverBeforeGame(String title,String message)throws IOException{
        PlaybackService service=active;
        if(service==null||!service.running)throw new IOException("本机服务未就绪；未打开游戏");
        if(service.overlay==null)service.overlay=new ReplayOverlay(service);
        service.overlay.show(title,message);service.coverShown=true;
    }
    static void consoleVisible(){PlaybackService service=active;if(service!=null){service.coverShown=false;if(service.overlay!=null)service.overlay.hide();}}
    private void updateCover(final JSONObject state,final String sourceHash,final String id){
        ui.post(new Runnable(){public void run(){try{
            String phase=state.optString("state","");
            if(PlaybackHandoff.verified(state,sourceHash,System.currentTimeMillis()/1000)){
                coverShown=false;if(overlay!=null)overlay.hide();
                PlaybackHandoff.recordStarted(PlaybackService.this,id,state);
            }else if(coverShown){
                if(phase.equals("complete")||phase.equals("needs_review")||phase.equals("cancelled")||phase.equals("stopped")||phase.equals("scene_left")||phase.equals("monitor_expired")){
                    coverShown=false;if(overlay!=null)overlay.hide();
                }else overlay.show(PlaybackStatus.title(state),state.optString("message","")+"\n确认开播后自动收起；不拦截游戏触摸。");
            }
        }catch(Exception ignored){coverShown=false;if(overlay!=null)overlay.hide();}}});
    }
    private static void save(Context context,JSONObject value)throws Exception{
        value.put("updated_at",System.currentTimeMillis()/1000);
        MainActivity.write(new File(context.getFilesDir(),"phone-service-state.json"),value.toString().getBytes(StandardCharsets.UTF_8));
    }
    static Notification progressNotification(Context context,String title,String message,boolean ongoing){
        Intent console=new Intent(context,MainActivity.class).addFlags(0x24000000);
        PendingIntent back=PendingIntent.getActivity(context,0,console,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(context,"phone-replay")
            .setSmallIcon(android.R.drawable.ic_media_play).setContentTitle(title)
            .setContentText(message).setStyle(new Notification.BigTextStyle().bigText(message))
            .setContentIntent(back).setOnlyAlertOnce(true).setOngoing(ongoing).build();
    }
    private void notice(String title,String message,boolean ongoing){
        Notification notification=progressNotification(this,title,message,ongoing);
        if(ongoing)startForeground(21,notification);
        else ((NotificationManager)getSystemService("notification")).notify(21,notification);
    }
    @Override public int onStartCommand(Intent intent,int flags,int startId){
        if(running)return START_NOT_STICKY;
        running=true;busy=true;active=this;
        NotificationManager notifications=(NotificationManager)getSystemService("notification");
        notifications.createNotificationChannel(new NotificationChannel("phone-replay","本机回放进度",NotificationManager.IMPORTANCE_LOW));
        notice("准备中 · 手机独立回放","准备阶段留在控制台；整局校验后显示悬浮进度并打开游戏。",true);
        final double speed=intent==null?1:intent.getDoubleExtra("speed",1);
        final String id=intent==null?"":intent.getStringExtra("request_id");
        final boolean replayRequested=intent!=null&&"yes".equals(intent.getStringExtra("replay_requested"));
        final String diagnostic=intent==null?"":intent.getStringExtra("diagnostic_prefix");
        final String queueId=armedQueueId;
        if(id!=null&&id.matches("[a-f0-9-]{36}")&&OverlayAccess.allowed(this))try{
            // Native preparation needs the client foreground, including the
            // automatically prepared row after a verified client refresh.
            // Starting this service never publishes a scene: the explicit play
            // request/source-bound foreground handoff is still required.
            FloatingConsole.start(this);
            FloatingConsole.note(this,"正在游戏大厅准备回放；就绪后可在悬浮窗播放。后台 HTML 解析可同时进行。");
            openGame(this);
        }catch(Exception e){FloatingConsole.note(this,"请打开游戏并进入大厅，原生准备会等待；队列已保存。");}
        new Thread(new Runnable(){public void run(){String finalTitle="任务已结束",finalMessage="点此返回控制台查看结果。";try{
            if(id==null||!id.matches("[a-f0-9-]{36}"))throw new IOException("缺少明确的本机请求；不恢复或自动重试旧任务");
            byte[] source=MainActivity.read(new FileInputStream(new File(getFilesDir(),"phone-requests/"+id+".html")),ReplaySource.MAX_BYTES);
            JSONObject job=NativePython.startPlayback(PlaybackService.this,source,speed,diagnostic==null?"":diagnostic,!queueId.isEmpty());
            save(PlaybackService.this,new JSONObject().put("state","queued").put("request_id",id).put("source_sha256",MainActivity.sha(source)).put("directory",job.getString("directory")).put("message","正在本机校验；尚未跳转游戏。"));
            File status=new File(job.getString("directory"),"status.json");
            boolean returnToConsole=false,completed=false;
            for(;;){
                if(status.isFile()){
                    JSONObject state=new JSONObject(MainActivity.text(status,32768));
                    String phase=state.optString("state","");
                    finalTitle=PlaybackStatus.title(state);finalMessage=PlaybackStatus.detail(state,System.currentTimeMillis()/1000);
                    notice(finalTitle,finalMessage,true);
                    updateCover(state,MainActivity.sha(source),id);
                    // Explicit Replay reopens the client; the Activity may now
                    // be backgrounded. Its same source/generation/overlay gate
                    // still applies before the FIRST scene publication.
                    boolean wanted=!queueId.isEmpty()&&queueId.equals(ConsoleActions.playWhenReady());
                    if(!queueId.isEmpty()&&!armedPlaying&&queueId.equals(cancelQueueId)&&PRE_SCENE.contains(phase)){
                        File stop=new File(status.getParentFile(),"stop-request.json");
                        if(!stop.exists()&&!new File(status.getParentFile(),"foreground-request.json").exists())
                            MainActivity.write(stop,new JSONObject().put("cancel_before_scene",true).put("reason","queue changed before playback was requested").toString().getBytes(StandardCharsets.UTF_8));
                    }else if((replayRequested||wanted)&&PlaybackHandoff.readyForForeground(state,MainActivity.sha(source),System.currentTimeMillis()/1000)&&NativePython.sameGameGeneration(state)){
                        if(wanted&&!armedPlaying){armedPlaying=true;ConsoleActions.armedStarted(PlaybackService.this,queueId,source);}
                        final File directory=status.getParentFile();final String hash=MainActivity.sha(source);
                        ui.post(new Runnable(){public void run(){try{PlaybackHandoff.serviceForeground(PlaybackService.this,id,hash,directory);}catch(Exception ignored){/* No scene is published without the signal. */}}});
                    }
                    if(phase.equals("complete")&&PlaybackStatus.completedVerified(status.getParentFile(),state)){
                        CompletedReplay.remember(PlaybackService.this,status.getParentFile());
                        if(NativePython.gameGenerationReleased(state))NativePython.recordRelease(PlaybackService.this,state);
                        completed=true;returnToConsole=returnsToConsole(state,true);break;
                    }
                    long age=System.currentTimeMillis()/1000-state.optLong("updated_at",0);
                    if(returnsToConsole(state,false))returnToConsole=true;
                    if(phase.equals("released")||phase.equals("stopped"))ConsoleActions.setAutomatic(PlaybackService.this,false);
                    if(phase.equals("released")||phase.equals("needs_review")||phase.equals("failed_before_native")||phase.equals("stopped")||phase.equals("cancelled")||phase.equals("scene_left")||phase.equals("monitor_expired")||(!state.optBoolean("monitor_active",true))||age>1800)break;
                }
                Thread.sleep(1500);
            }
            // Return after the runtime has released its lease; Replay/Exit belong in the visible console.
            if(returnToConsole){
                // One automatic return for this exact request; never restart or
                // replay it here. User chooses Replay/Exit in the Activity.
                final File returned=new File(getFilesDir(),"phone-requests/"+id+"-returned.json");
                if(!returned.exists()){
                    MainActivity.write(returned,new JSONObject().put("request_id",id).put("terminal_verified",completed).put("source_sha256",MainActivity.sha(source)).toString().getBytes(StandardCharsets.UTF_8));
                    ui.post(new Runnable(){public void run(){try{startActivity(new Intent(PlaybackService.this,MainActivity.class).addFlags(0x34000000));}catch(Exception ignored){/* Tappable completion notification remains. */}}});
                }
            }
        }catch(Exception error){try{
            finalTitle="未开始播放 / 任务异常";finalMessage=error.toString();
            save(PlaybackService.this,new JSONObject().put("state","request_failed").put("message",finalMessage));
        }catch(Exception ignored){}
        }finally{
            String ended=queueId;boolean played=armedPlaying,cancelled=!ended.isEmpty()&&ended.equals(cancelQueueId);
            armedQueueId="";armedPlaying=false;running=false;busy=false;
            ConsoleActions.armedEnded(PlaybackService.this,ended,played,cancelled,finalTitle);
            ui.post(new Runnable(){public void run(){coverShown=false;if(overlay!=null)overlay.hide();}});stopForeground(true);notice(finalTitle,finalMessage,false);stopSelf();
            // After this instance stops: prepare the next queue row in advance (once per game process); never plays by itself.
            final Context app=getApplicationContext();
            new Thread(new Runnable(){public void run(){try{Thread.sleep(1500);}catch(InterruptedException ignored){}ConsoleActions.autoPrepare(app);}}).start();
        }}}).start();
        return START_NOT_STICKY;
    }
    @Override public IBinder onBind(Intent intent){return null;}
    @Override public void onDestroy(){coverShown=false;if(overlay!=null)overlay.hide();if(active==this)active=null;super.onDestroy();}
}
