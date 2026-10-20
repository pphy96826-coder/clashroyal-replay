package local.royale.replay.android;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.graphics.PixelFormat;
import android.os.Handler;
import android.os.IBinder;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.widget.*;
import java.io.File;
import java.nio.charset.StandardCharsets;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Floating console over the game: a draggable bubble that expands into playback
 * and queue controls. Touchable only inside its own bounds and never focusable,
 * so game input outside it is untouched. Same action gates as MainActivity.
 */
public final class FloatingConsole extends Service {
    private static final String TOGGLE="local.royale.replay.android.FLOATING_TOGGLE";
    private static final int BUBBLE=52,PANEL=330;
    private static volatile FloatingConsole active;
    private static volatile String note="";
    private final Handler ui=new Handler();
    private WindowManager window;
    private WindowManager.LayoutParams params;
    private LinearLayout root,panel,queueList;
    private ScrollView queueScroll;
    private TextView bubble,status,detail,noteView,queueTitle;
    private Button next,speed,stop,clear;
    private boolean expanded,closed,working;
    private int bubbleX,bubbleY,bubbleColor;
    private long stopArmedUntil,clearArmedUntil;
    private String queueShown;
    private final Runnable refresh=new Runnable(){public void run(){if(!closed){update();ui.postDelayed(this,1000);}}};

    static boolean enabled(Context context){
        try{return new JSONObject(MainActivity.text(new File(context.getFilesDir(),"floating-console.json"),4096)).optBoolean("enabled",true);}catch(Exception e){return true;}
    }
    static void setEnabled(Context context,boolean on)throws Exception{
        MainActivity.write(new File(context.getFilesDir(),"floating-console.json"),new JSONObject().put("enabled",on).toString().getBytes(StandardCharsets.UTF_8));
    }
    static boolean running(){return active!=null;}
    static void start(Context context){if(OverlayAccess.allowed(context))context.startForegroundService(new Intent(context,FloatingConsole.class));}
    static void shutdown(Context context){context.stopService(new Intent(context,FloatingConsole.class));}
    /** Any thread; reopens the panel (collapsed while the picker was open) to show the result. */
    static void note(Context context,String message){
        note=message==null?"":message;final FloatingConsole service=active;
        if(service!=null)service.ui.post(new Runnable(){public void run(){if(!service.expanded)service.setExpanded(true);else{service.queueShown=null;service.update();}}});
    }

    @Override public int onStartCommand(Intent intent,int flags,int startId){
        active=this;
        NotificationManager notifications=(NotificationManager)getSystemService("notification");
        notifications.createNotificationChannel(new NotificationChannel("floating-console","悬浮控制台",NotificationManager.IMPORTANCE_LOW));
        PendingIntent toggle=PendingIntent.getService(this,1,new Intent(this,FloatingConsole.class).setAction(TOGGLE),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        startForeground(22,new Notification.Builder(this,"floating-console").setSmallIcon(android.R.drawable.ic_media_play)
            .setContentTitle("回放悬浮控制台").setContentText("点此展开或收起；拖动圆形按钮可移动位置。").setContentIntent(toggle).setOngoing(true).build());
        if(!OverlayAccess.allowed(this)){stopSelf();return START_NOT_STICKY;}
        try{
            if(root==null)attach();
            if(intent!=null&&TOGGLE.equals(intent.getAction()))setExpanded(!expanded);
        }catch(RuntimeException e){root=null;stopSelf();}
        return START_NOT_STICKY;
    }
    private int dp(int value){return QueueRows.dp(this,value);}
    private int screenWidth(){return getResources().getDisplayMetrics().widthPixels;}
    private int screenHeight(){return getResources().getDisplayMetrics().heightPixels;}
    private static int clamp(int value,int low,int high){return Math.max(low,Math.min(value,Math.max(low,high)));}
    private TextView text(LinearLayout parent,String value,int size,int color){
        TextView t=new TextView(this);t.setText(value);t.setTextSize(size);t.setTextColor(color);t.setPadding(0,dp(2),0,dp(4));parent.addView(t);return t;
    }
    private LinearLayout row(){
        LinearLayout r=new LinearLayout(this);r.setOrientation(0);r.setPadding(0,dp(4),0,dp(2));panel.addView(r,new LinearLayout.LayoutParams(-1,-2));return r;
    }
    private Button chip(LinearLayout parent,String value,int color,View.OnClickListener listener){
        Button b=QueueRows.chip(this,value,color,listener);
        LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(0,-2,1f);p.setMargins(dp(3),0,dp(3),0);parent.addView(b,p);return b;
    }
    private void attach(){
        window=(WindowManager)getSystemService("window");
        root=new LinearLayout(this);root.setOrientation(1);
        bubble=new TextView(this);bubble.setText("回放");bubble.setTextSize(14);bubble.setTextColor(0xffffffff);bubble.setGravity(Gravity.CENTER);
        bubble.setOnTouchListener(new Drag());
        root.addView(bubble,new LinearLayout.LayoutParams(dp(BUBBLE),dp(BUBBLE)));
        panel=new LinearLayout(this);panel.setOrientation(1);panel.setPadding(dp(12),dp(10),dp(12),dp(12));panel.setBackground(QueueRows.shape(this,0xfa101b2e,14));
        text(panel,"回放悬浮控制台 · 点圆形按钮收起",13,0xff9aaec8);
        status=text(panel,"",16,0xff80e8d5);
        detail=text(panel,"",12,0xffb4c4da);detail.setMaxLines(4);
        noteView=text(panel,"",12,0xffffd27a);noteView.setMaxLines(3);
        LinearLayout playback=row();
        next=chip(playback,"播放下一个",0xff177e6c,new View.OnClickListener(){public void onClick(View v){
            work(new Job(){public String run()throws Exception{ConsoleActions.playNext(FloatingConsole.this);return "已请求队列下一场；先完成场景校验，不重复提交原生任务。";}});}});
        speed=chip(playback,ConsoleActions.speedLabel(),0xff2c4a6e,new View.OnClickListener(){public void onClick(View v){ConsoleActions.cycleSpeed();update();}});
        LinearLayout stopRow=row();
        stop=chip(stopRow,"停止当前回放",0xff8a3340,new View.OnClickListener(){public void onClick(View v){
            if(System.currentTimeMillis()>stopArmedUntil){stopArmedUntil=System.currentTimeMillis()+4000;update();return;}
            stopArmedUntil=0;work(new Job(){public String run()throws Exception{ConsoleActions.requestStop(FloatingConsole.this);return "已请求停止 · 等待安全边界确认";}});}});
        queueTitle=text(panel,"",14,0xfff0f5ff);
        queueScroll=new ScrollView(this);queueList=new LinearLayout(this);queueList.setOrientation(1);queueScroll.addView(queueList);
        panel.addView(queueScroll,new LinearLayout.LayoutParams(-1,-2));
        LinearLayout edit=row();
        chip(edit,"添加 HTML",0xff177e6c,new View.OnClickListener(){public void onClick(View v){
            try{setExpanded(false);startActivity(new Intent(FloatingConsole.this,QueueImportActivity.class).addFlags(0x10000000));}catch(Exception e){note="无法打开文件选择器："+e.getMessage();setExpanded(true);}}});
        clear=chip(edit,"清空队列",0xff8a3340,new View.OnClickListener(){public void onClick(View v){
            if(System.currentTimeMillis()>clearArmedUntil){clearArmedUntil=System.currentTimeMillis()+4000;update();return;}
            clearArmedUntil=0;try{note="已清空队列 "+ConsoleActions.clearQueue(FloatingConsole.this)+" 场；不影响正在播放的回放。";}catch(Exception e){note="未清空："+e.getMessage();}queueShown=null;update();}});
        LinearLayout exits=row();
        chip(exits,"完整控制台",0xff2c4a6e,new View.OnClickListener(){public void onClick(View v){
            setExpanded(false);startActivity(new Intent(FloatingConsole.this,MainActivity.class).addFlags(0x34000000));}});
        chip(exits,"关闭悬浮窗",0xff3a4558,new View.OnClickListener(){public void onClick(View v){
            try{setEnabled(FloatingConsole.this,false);}catch(Exception ignored){}stopSelf();}});
        panel.setVisibility(View.GONE);
        root.addView(panel,new LinearLayout.LayoutParams(Math.min(dp(PANEL),screenWidth()-dp(12)),-2));
        params=new WindowManager.LayoutParams(-2,-2,WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE|WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,PixelFormat.TRANSLUCENT);
        params.gravity=Gravity.TOP|Gravity.LEFT;
        bubbleX=screenWidth()-dp(BUBBLE)-dp(6);bubbleY=screenHeight()/3;params.x=bubbleX;params.y=bubbleY;
        root.setGravity(Gravity.RIGHT);
        window.addView(root,params);
        ui.post(refresh);
    }
    private boolean onRight(){return bubbleX+dp(BUBBLE)/2>screenWidth()/2;}
    private int panelWidth(){return Math.min(dp(PANEL),screenWidth()-dp(12));}
    private void place(){
        boolean right=onRight();root.setGravity(right?Gravity.RIGHT:Gravity.LEFT);
        if(expanded){int width=panelWidth();params.x=clamp(right?bubbleX+dp(BUBBLE)-width:bubbleX,0,screenWidth()-width);params.y=clamp(bubbleY,0,screenHeight()-dp(600));}
        else{params.x=bubbleX;params.y=bubbleY;}
        window.updateViewLayout(root,params);
    }
    private void setExpanded(boolean on){
        if(root==null)return;
        expanded=on;panel.setVisibility(on?View.VISIBLE:View.GONE);stopArmedUntil=0;clearArmedUntil=0;
        place();if(on){queueShown=null;update();}
    }
    /** Short taps toggle the panel; drags move the whole window, then remember the bubble spot. */
    private final class Drag implements View.OnTouchListener {
        private float downX,downY;private int startX,startY;private boolean moved;
        public boolean onTouch(View v,MotionEvent event){
            int action=event.getAction()&0xff;
            if(action==MotionEvent.ACTION_DOWN){downX=event.getRawX();downY=event.getRawY();startX=params.x;startY=params.y;moved=false;}
            else if(action==MotionEvent.ACTION_MOVE){
                int dx=(int)(event.getRawX()-downX),dy=(int)(event.getRawY()-downY);
                if(!moved&&Math.abs(dx)<dp(8)&&Math.abs(dy)<dp(8))return true;
                moved=true;int width=expanded?panelWidth():dp(BUBBLE);
                params.x=clamp(startX+dx,0,screenWidth()-width);params.y=clamp(startY+dy,0,screenHeight()-dp(BUBBLE));
                window.updateViewLayout(root,params);
            }else if(action==MotionEvent.ACTION_UP){
                if(!moved){setExpanded(!expanded);return true;}
                bubbleX=expanded&&onRight()?params.x+panelWidth()-dp(BUBBLE):params.x;bubbleY=params.y;
                if(!expanded)place();
            }
            return true;
        }
    }
    private interface Job {String run()throws Exception;}
    private void work(final Job job){
        if(working)return;working=true;queueShown=null;update();
        new Thread(new Runnable(){public void run(){String message;
            try{message=job.run();}catch(Exception e){message="未完成："+e.getMessage();}
            final String result=message;
            ui.post(new Runnable(){public void run(){working=false;note=result;queueShown=null;update();}});
        }}).start();
    }
    private void update(){
        if(root==null||closed)return;
        try{
            JSONObject state=PlaybackStatus.read(this);
            boolean owns=PlaybackStatus.ownsTask(state);
            int color=owns?0xf0d9822b:0xf0177e6c;
            if(color!=bubbleColor){bubbleColor=color;bubble.setBackground(QueueRows.shape(this,color,BUBBLE/2));}
            if(!expanded)return;
            long now=System.currentTimeMillis();
            status.setText(PlaybackStatus.title(state));detail.setText(PlaybackStatus.detail(state,now/1000));
            noteView.setText(note);noteView.setVisibility(note.isEmpty()?View.GONE:View.VISIBLE);
            JSONArray rows=ReplayQueue.rows(getFilesDir());
            boolean editable=!working&&!ConsoleActions.starting();
            queueTitle.setText("待播队列："+rows.length()+" 场"+(rows.length()>0?" · 下一场在最上面":""));
            String shown=rows.toString()+editable;
            if(!shown.equals(queueShown)){
                queueShown=shown;
                QueueRows.render(this,queueList,rows,editable,new QueueRows.Listener(){public void changed(String message){note=message;queueShown=null;update();}});
                queueScroll.setLayoutParams(new LinearLayout.LayoutParams(-1,rows.length()>5?dp(200):-2));
            }
            QueueRows.enable(next,rows.length()>0&&!working&&ConsoleActions.canPlayNext(state));
            speed.setText(ConsoleActions.speedLabel());QueueRows.enable(speed,!working&&!PlaybackService.isBusy());
            stop.setVisibility(PlaybackStatus.canStop(state,now/1000)?View.VISIBLE:View.GONE);
            stop.setText(now<stopArmedUntil?"再点一次确认停止（仅重启游戏客户端）":"停止当前回放");
            clear.setText(now<clearArmedUntil?"再点一次确认清空":"清空队列");QueueRows.enable(clear,rows.length()>0&&editable);
        }catch(Exception e){if(expanded)status.setText("状态暂不可读；不会自动重试回放。");}
    }
    @Override public IBinder onBind(Intent intent){return null;}
    @Override public void onDestroy(){
        closed=true;ui.removeCallbacks(refresh);
        if(root!=null){try{window.removeView(root);}catch(RuntimeException ignored){}root=null;}
        if(active==this)active=null;super.onDestroy();
    }
}
