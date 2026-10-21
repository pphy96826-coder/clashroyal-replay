package local.royale.replay.android;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.view.View;
import android.widget.*;

/** Exported review screen only. External links never authorize root/native execution. */
public final class BrowserImportActivity extends Activity {
    private volatile boolean closed;
    private TextView status,detail;
    private Button play,speedButton;
    private BrowserImport.Snapshot snapshot;
    private int speedIndex=2;
    private final double[] speeds={.25,.5,1,2,4};
    @Override public void onCreate(Bundle state){
        super.onCreate(state);setTitle("浏览器回放导入");
        LinearLayout root=new LinearLayout(this);root.setOrientation(1);root.setPadding(26,30,26,24);
        ScrollView scroll=new ScrollView(this);scroll.addView(root);setContentView(scroll);
        status=new TextView(this);status.setTextSize(22);status.setText("正在校验浏览器发送的回放…");root.addView(status);
        detail=new TextView(this);detail.setPadding(0,24,0,24);root.addView(detail);
        play=new Button(this);play.setText("确认播放本场回放");play.setEnabled(false);root.addView(play);
        speedButton=new Button(this);speedButton.setText("播放倍速：1×");root.addView(speedButton);
        speedButton.setOnClickListener(new View.OnClickListener(){public void onClick(View v){speedIndex=(speedIndex+1)%speeds.length;speedButton.setText("播放倍速："+speeds[speedIndex]+"×");}});
        Button cancel=new Button(this);cancel.setText("取消，返回浏览器");root.addView(cancel);
        cancel.setOnClickListener(new View.OnClickListener(){public void onClick(View v){finish();}});
        play.setOnClickListener(new View.OnClickListener(){public void onClick(View v){
            if(snapshot==null)return;
            if(!OverlayAccess.ensure(BrowserImportActivity.this)){status.setText("请允许悬浮进度卡，返回后再次确认播放。");return;}
            play.setEnabled(false);speedButton.setEnabled(false);
            try{
                boolean started=PlaybackService.submitOrQueue(BrowserImportActivity.this,snapshot.html,speeds[speedIndex]);
                if(started){startActivity(new Intent(BrowserImportActivity.this,MainActivity.class));finish();}
                else{
                    status.setText("已加入待播队列 · 本场尚未播放");
                    detail.setText("已保存本场 HTML；当前任务保持不变。上一场结束后，在控制台点击“播放下一个”。\n队列待播："+ReplayQueue.rows(getFilesDir()).length()+" 场。");
                    play.setText("本场已入队");
                }
            }catch(Exception e){status.setText("未开始播放："+e.getMessage());play.setEnabled(true);speedButton.setEnabled(true);}
        }});
        // Read only the URI; no Intent extras can request autoplay, shell, paths or restart.
        final String link=getIntent().getData()==null?null:getIntent().getData().toString();
        new Thread(new Runnable(){public void run(){try{
            final BrowserImport.Snapshot checked=BrowserImport.decode(link);
            runOnUiThread(new Runnable(){public void run(){if(closed)return;snapshot=checked;
                status.setText("已接收回放 "+checked.source.tag);
                detail.setText(checked.source.count()+" 条源指令 · "+checked.html.length+" 字节 HTML\n"+
                    "来源（发送方声明）："+checked.url+"\n\n内容校验通过不代表网站身份认证。请确认这是你刚才选择的对局。\n"+
                    "只有点击下方确认才会调用本机播放；不会运行网页脚本、上传 HTML 或读取 Cookie。已有对局不会被覆盖。");
                play.setEnabled(true);
                try{if(PlaybackService.isBusy()||PlaybackStatus.ownsTask(PlaybackStatus.read(BrowserImportActivity.this)))play.setText("确认加入待播队列");}catch(Exception ignored){}
            }});
        }catch(final Exception e){runOnUiThread(new Runnable(){public void run(){if(!closed){status.setText("未导入："+e.getMessage());detail.setText("没有播放旧文件，也没有提交原生任务。请回浏览器重新发送，或在控制台选择已保存的 HTML。");}}});}}}).start();
    }
    @Override protected void onDestroy(){closed=true;snapshot=null;super.onDestroy();}
}
