package local.royale.replay.android;

import android.content.Context;
import android.graphics.drawable.GradientDrawable;
import android.view.Gravity;
import android.view.View;
import android.widget.*;
import org.json.JSONArray;
import org.json.JSONObject;

/** Editable queue rows (置顶 / 删除) shared by the console and the floating window. */
final class QueueRows {
    interface Listener {void changed(String message);}
    static int dp(Context context,int value){return Math.round(value*context.getResources().getDisplayMetrics().density);}
    static GradientDrawable shape(Context context,int color,int radius){GradientDrawable shape=new GradientDrawable();shape.setColor(color);shape.setCornerRadius(dp(context,radius));return shape;}
    static Button chip(Context context,String value,int color,View.OnClickListener listener){
        Button b=new Button(context);b.setText(value);b.setTextSize(13);b.setTextColor(0xffffffff);b.setBackground(shape(context,color,8));
        b.setAllCaps(false);b.setMinHeight(0);b.setMinimumHeight(0);b.setMinWidth(0);b.setMinimumWidth(0);
        b.setPadding(dp(context,10),dp(context,7),dp(context,10),dp(context,7));b.setOnClickListener(listener);return b;
    }
    static void enable(View view,boolean on){view.setEnabled(on);view.setAlpha(on?1f:.4f);}
    static void render(final Context context,LinearLayout list,JSONArray rows,java.util.Map<String,String> statuses,boolean compact,boolean editable,final Listener listener)throws Exception{
        list.removeAllViews();
        for(int i=0;i<rows.length();i++){
            JSONObject row=rows.getJSONObject(i);final String id=row.optString("id","");final String tag=row.optString("tag","");
            LinearLayout line=new LinearLayout(context);line.setOrientation(0);line.setGravity(Gravity.CENTER_VERTICAL);line.setPadding(0,dp(context,3),0,dp(context,3));
            TextView name=new TextView(context);name.setTextSize(13);name.setTextColor(0xffeef5ff);name.setSingleLine(true);
            name.setText((i+1)+". "+tag+(compact?"":" · "+row.optLong("events",0)+" 条")+(row.optBoolean("diagnostic_only",false)?"（诊断）":""));
            line.addView(name,new LinearLayout.LayoutParams(0,-2,1f));
            String label=statuses.containsKey(id)?statuses.get(id):"";
            if(!label.isEmpty()){
                TextView state=new TextView(context);state.setTextSize(11);state.setSingleLine(true);state.setText(label);
                state.setTextColor(label.startsWith("⚠")?0xffff8a80:label.startsWith("✓")||label.equals("正在开播")?0xff80e8d5:label.startsWith("准备中")?0xffffd27a:0xff9aaec8);
                line.addView(state,gap(context));
            }
            if(i>0){Button top=chip(context,"置顶",0xff2c4a6e,new View.OnClickListener(){public void onClick(View v){
                try{ConsoleActions.moveQueuedToFront(context,id);listener.changed("已将 "+tag+" 提前（已就绪的那场仍先播）");}catch(Exception e){listener.changed("未改变队列："+e.getMessage());}}});
                enable(top,editable);line.addView(top,gap(context));}
            Button remove=chip(context,"删除",0xff8a3340,new View.OnClickListener(){public void onClick(View v){
                try{ConsoleActions.removeQueued(context,id);listener.changed("已从队列删除 "+tag+"；不影响正在播放的回放。");}catch(Exception e){listener.changed("未改变队列："+e.getMessage());}}});
            enable(remove,editable);line.addView(remove,gap(context));
            list.addView(line);
        }
        if(rows.length()==0){TextView empty=new TextView(context);empty.setTextSize(13);empty.setTextColor(0xff9aaec8);empty.setText("队列为空 · 点“添加 HTML”选择文件");list.addView(empty);}
    }
    static LinearLayout.LayoutParams gap(Context context){LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-2,-2);p.setMargins(dp(context,6),0,0,0);return p;}
    private QueueRows(){}
}
