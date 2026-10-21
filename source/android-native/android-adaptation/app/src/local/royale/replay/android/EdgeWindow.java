package local.royale.replay.android;

import android.app.ActivityOptions;
import android.content.Context;
import android.content.Intent;
import android.graphics.Rect;
import java.io.IOException;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Opens the user's own Edge (its Google/RoyaleAPI login stays in Edge) as a
 * system freeform window over the game. The window, caption bar and close /
 * maximize buttons belong to the system; nothing here reads Edge's content.
 */
final class EdgeWindow {
    static final String EDGE="com.microsoft.emmx";
    // Fixed commands only: no text from the page, intent or user reaches the shell.
    private static final String START="am start --windowingMode 5 -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -p "+EDGE;
    private static final Pattern TASK=Pattern.compile("taskId=(\\d{1,9}): "+Pattern.quote(EDGE)+"/");
    static boolean installed(Context context){return context.getPackageManager().getLaunchIntentForPackage(EDGE)!=null;}
    /** Off the UI thread. Returns a note when only a normal (maybe fullscreen) window could be opened. */
    static String open(Context context)throws Exception{
        if(!installed(context))throw new IOException("未安装 Microsoft Edge");
        int width=context.getResources().getDisplayMetrics().widthPixels,height=context.getResources().getDisplayMetrics().heightPixels;
        int left=width/27,top=height/2,right=width-width/27,bottom=height-height/40;
        try{
            // Public APIs cannot move an existing fullscreen task into freeform; the shell can.
            StandaloneDoctor.Output started=StandaloneDoctor.root(START,10);
            if(started.code!=0||started.text.contains("Error"))throw new IOException(started.text);
            Matcher task=TASK.matcher(StandaloneDoctor.root("am stack list",10).text);
            if(!task.find())throw new IOException("未找到 Edge 窗口");
            StandaloneDoctor.root("am task resize "+Integer.parseInt(task.group(1))+" "+left+" "+top+" "+right+" "+bottom,10);
            return null;
        }catch(Exception rootUnavailable){
            Intent edge=context.getPackageManager().getLaunchIntentForPackage(EDGE).addFlags(0x10000000);
            context.startActivity(edge,ActivityOptions.makeBasic().setLaunchBounds(new Rect(left,top,right,bottom)).toBundle());
            return "已打开 Edge；系统未允许小窗时会全屏，可用底部返回键回到游戏。";
        }
    }
    private EdgeWindow(){}
}
