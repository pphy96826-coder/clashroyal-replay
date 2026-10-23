package local.royale.replay.android;

import android.app.Instrumentation;
import android.os.Bundle;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import org.json.JSONObject;

/** Explicit reset acceptance: preserve the login and remove an owned stopped parser. */
public final class ResetIntegrationTests extends Instrumentation {
    @Override public void onCreate(Bundle args){super.onCreate(args);start();}
    private String quote(File file)throws Exception{return "'"+file.getCanonicalPath().replace("'","'\\''")+"'";}
    @Override public void onStart(){Bundle result=new Bundle();try{
        JSONObject game=NativePython.currentGameGeneration();
        File files=getTargetContext().getFilesDir(),source=new File(files,"source.html");
        byte[] raw=MainActivity.read(new FileInputStream(source),ReplaySource.MAX_BYTES);String hash=MainActivity.sha(raw);
        int queue=ReplayQueue.rows(files).length();
        String idle=ReplayReset.reset(getTargetContext());
        if(!NativePython.sameGameGeneration(game))throw new AssertionError("idle reset restarted the logged-in game");
        File home=NativePython.sourceRuntime(getTargetContext());
        File action=new File(new File(files,"local-imports"),UUID.randomUUID().toString());if(!action.mkdir())throw new IOException("test input directory");
        File input=new File(action,"input.html");MainActivity.write(input,raw);
        File binary=new File(home,"app/mumu-support/runtime/bin/phone_runtime"),log=new File(action,"reset-parser.log");
        String command="LD_LIBRARY_PATH="+quote(new File(home,"app/mumu-support/runtime/lib"))+" "+quote(binary)+" import-source "+quote(home)+" "+quote(input)+" "+quote(new File(action,"result"))+" - >"+quote(log)+" 2>&1 & echo $!";
        StandaloneDoctor.Output launched=StandaloneDoctor.root(command,10);
        if(launched.code!=0||!launched.text.matches("[1-9][0-9]*"))throw new IOException("parser did not launch");
        int pid=Integer.parseInt(launched.text);
        StandaloneDoctor.Output args=StandaloneDoctor.root("cat /proc/"+pid+"/cmdline",5);
        if(args.code!=0||!args.text.contains(input.getCanonicalPath()))throw new IOException("parser ended before pause; no unknown PID touched");
        String generation=StandaloneDoctor.startTime(StandaloneDoctor.root("cat /proc/"+pid+"/stat",5));
        if(StandaloneDoctor.root("kill -STOP "+pid,5).code!=0)throw new IOException("parser pause failed");
        String reset=ReplayReset.reset(getTargetContext());
        StandaloneDoctor.Output after=StandaloneDoctor.root("if test -d /proc/"+pid+"; then cat /proc/"+pid+"/stat; else printf ABSENT; fi",5);
        if(after.code!=0||(!after.text.equals("ABSENT")&&StandaloneDoctor.startTime(after).equals(generation)))throw new AssertionError("owned paused parser still present");
        if(!NativePython.sameGameGeneration(game))throw new AssertionError("parser reset restarted the game");
        if(ReplayQueue.rows(files).length()!=queue||!hash.equals(MainActivity.sha(MainActivity.read(new FileInputStream(source),ReplaySource.MAX_BYTES))))throw new AssertionError("reset changed saved replay or queue");
        if(ReplayReset.blocked(getTargetContext())||PlaybackService.isBusy())throw new AssertionError("reset lease still busy");
        result.putString("summary","PASS idle reset + stopped owned parser reset; login generation, replay and queue preserved; no native battle submitted");
        result.putString("reset_message",reset);finish(-1,result);
    }catch(Throwable error){result.putString("error",error.toString());finish(0,result);}}
}
