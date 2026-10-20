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
            try{FloatingConsole.offer(BrowserBridgeActivity.this,BrowserImport.decode(link));}
            catch(Exception e){FloatingConsole.note(BrowserBridgeActivity.this,"未导入 Edge 回放："+e.getMessage()+"；没有播放或保存。");}
            runOnUiThread(new Runnable(){public void run(){finish();}});
        }}).start();
    }
}
