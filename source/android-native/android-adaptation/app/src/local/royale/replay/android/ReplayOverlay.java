package local.royale.replay.android;

import android.content.Context;
import android.graphics.PixelFormat;
import android.view.Gravity;
import android.view.WindowManager;
import android.widget.LinearLayout;
import android.widget.TextView;

/** Read-only, touch-through loading card. No screen capture or input capture. */
final class ReplayOverlay {
    private final Context context;
    private final WindowManager window;
    private LinearLayout card;
    private TextView title,detail;
    ReplayOverlay(Context context){this.context=context;window=(WindowManager)context.getSystemService("window");}
    void show(String heading,String message){
        if(!OverlayAccess.allowed(context))throw new SecurityException("请先在系统中允许控制台显示悬浮进度");
        if(card==null){
            card=new LinearLayout(context);card.setOrientation(1);card.setPadding(24,18,24,18);card.setBackgroundColor(0xf2101b2e);
            title=new TextView(context);title.setTextSize(19);title.setTextColor(0xff80e8d5);card.addView(title);
            detail=new TextView(context);detail.setTextSize(14);detail.setTextColor(0xffeef5ff);card.addView(detail);
            WindowManager.LayoutParams params=new WindowManager.LayoutParams(-1,-2,WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE|WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE,PixelFormat.TRANSLUCENT);
            params.gravity=Gravity.TOP|Gravity.CENTER_HORIZONTAL;params.y=80;
            // Android 12's untrusted-touch policy uses window opacity, not just
            // the card colour. One <=0.8 touch-through overlay stays non-blocking.
            params.alpha=0.75f;
            title.setText(heading);detail.setText(message);
            try{window.addView(card,params);}catch(RuntimeException e){card=null;throw e;}
        }else{title.setText(heading);detail.setText(message);}
    }
    void hide(){if(card!=null){try{window.removeView(card);}finally{card=null;title=null;detail=null;}}}
}
