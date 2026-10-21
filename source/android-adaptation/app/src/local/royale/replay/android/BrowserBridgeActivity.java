package local.royale.replay.android;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;

/**
 * Exported receiver for the Edge bridge link. Invisible: it only decodes the
 * link and hands the checked replay to the floating console, where the user
 * still chooses play / queue / ignore. Reads only the URI; extras are ignored.
 * Without the floating console it forwards to the original review screen.
 */
public final class BrowserBridgeActivity extends Activity {
    @Override public void onCreate(Bundle state){
        super.onCreate(state);
        if(state!=null){finish();return;}
        if(!OverlayAccess.allowed(this)||!(FloatingConsole.running()||FloatingConsole.enabled(this))){
            startActivity(new Intent(this,BrowserImportActivity.class).setData(getIntent().getData()));finish();return;
        }
        if(!FloatingConsole.running())FloatingConsole.start(this);
        final String link=getIntent().getData()==null?null:getIntent().getData().toString();
        new Thread(new Runnable(){public void run(){
            try{
                BrowserImport.Snapshot snapshot=BrowserImport.decode(link);
                String id=ReplayQueue.add(getFilesDir(),snapshot.html,snapshot.source);
                ConsoleActions.imported(BrowserBridgeActivity.this);
                FloatingConsole.note(BrowserBridgeActivity.this,"已收到回放 "+snapshot.source.tag+"，已自动加入准备队列；在悬浮窗点「播放下一个」即可播放。");
                runOnUiThread(new Runnable(){public void run(){try{PlaybackService.openGame(BrowserBridgeActivity.this);}catch(Exception e){FloatingConsole.note(BrowserBridgeActivity.this,"回放已保存；打开游戏后可在悬浮窗播放。");}}});
            }
            catch(Exception e){FloatingConsole.note(BrowserBridgeActivity.this,"未导入 Edge 回放："+e.getMessage()+"；没有播放或保存。");}
            runOnUiThread(new Runnable(){public void run(){finish();}});
        }}).start();
    }
}
