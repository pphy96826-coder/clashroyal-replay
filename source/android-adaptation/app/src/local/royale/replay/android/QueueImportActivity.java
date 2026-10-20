package local.royale.replay.android;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;

/** Picker-only task for the floating console; finishes back to whatever was in front (the game). */
public final class QueueImportActivity extends Activity {
    @Override public void onCreate(Bundle state){
        super.onCreate(state);
        if(state!=null)return; // Recreated while the picker is open; its result still arrives.
        try{
            Intent intent=new Intent("android.intent.action.OPEN_DOCUMENT");intent.addCategory("android.intent.category.OPENABLE");
            intent.setType("*/*");intent.addFlags(1);intent.putExtra("android.intent.extra.ALLOW_MULTIPLE",true);startActivityForResult(intent,42);
        }catch(Exception e){FloatingConsole.note(this,"无法打开文件选择器："+e.getMessage());finish();}
    }
    @Override protected void onActivityResult(int request,int result,final Intent data){
        super.onActivityResult(request,result,data);
        if(request!=42||result!=RESULT_OK||data==null){FloatingConsole.note(this,"已取消添加；队列未改变。");finish();return;}
        FloatingConsole.note(this,"正在解析所选 HTML…");
        // Read grants belong to this task, so finish only after every file is copied.
        new Thread(new Runnable(){public void run(){String message;
            try{message="已加入队列 "+ReplayQueue.importFrom(QueueImportActivity.this,data)+" 场；会自动提前准备第一场。";}catch(Exception e){message=e.getMessage();}
            ConsoleActions.autoPrepareLater(getApplicationContext());
            FloatingConsole.note(QueueImportActivity.this,message);
            runOnUiThread(new Runnable(){public void run(){finish();}});
        }}).start();
    }
}
