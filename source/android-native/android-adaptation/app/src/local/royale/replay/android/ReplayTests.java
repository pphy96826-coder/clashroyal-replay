package local.royale.replay.android;
import android.app.Instrumentation;
import android.os.Bundle;

public final class ReplayTests extends Instrumentation {
    @Override public void onCreate(Bundle args){super.onCreate(args);start();}
    @Override public void onStart(){Bundle report=new Bundle();int tests=0;try{
        String html=new String(MainActivity.read(getTargetContext().getAssets().open("synthetic.html"),ReplaySource.MAX_BYTES),"UTF-8");
        ReplaySource.Info info=ReplaySource.parse(html);
        if(info.plays!=3||info.abilities!=1||info.count()!=4||info.firstTick!=100||info.lastTick!=160)throw new AssertionError("source event mismatch");tests++;
        if(!info.events.get(0).get("data-t").equals("100"))throw new AssertionError("raw time changed");tests++;
        boolean rejected=false;try{ReplaySource.parse("<html>no timeline</html>");}catch(IllegalArgumentException ok){rejected=true;}if(!rejected)throw new AssertionError("invalid HTML accepted");tests++;
        rejected=false;try{ReplaySource.parse(html.replace("data-x=\"3500\"","data-x=\"18000\""));}catch(IllegalArgumentException ok){rejected=true;}if(!rejected)throw new AssertionError("out of bounds accepted");tests++;
        ReplaySource.Info ignored=ReplaySource.parse("<script>"+html+"</script>"+html);if(ignored.count()!=4)throw new AssertionError("script executed as events");tests++;
        ReplaySource.Info arena=ReplaySource.parse(html.replace("data-s=\"blue\"","data-s=\"t\"").replace("data-s=\"red\"","data-s=\"o\""));if(arena.count()!=4||!arena.events.get(0).get("data-s").equals("t"))throw new AssertionError("arena side identity changed");tests++;
        report.putString("summary","PASS "+tests+" device parser tests; native playback NOT tested");finish(-1,report);
    }catch(Throwable error){report.putString("error",error.toString());finish(0,report);}}
}
