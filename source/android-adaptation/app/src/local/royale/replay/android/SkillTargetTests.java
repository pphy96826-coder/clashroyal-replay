package local.royale.replay.android;
import android.app.Instrumentation;
import android.os.Bundle;
import java.io.*;
import org.json.JSONObject;

/** Explicit user-requested native simulation; never publishes a battle scene. */
public final class SkillTargetTests extends Instrumentation {
 private boolean freeCheckpoint;
 private boolean adaptiveSearch;
 private String checkpointSeed="";
 @Override public void onCreate(Bundle args){super.onCreate(args);freeCheckpoint="free-checkpoint".equals(args.getString("mode",""));adaptiveSearch="adaptive".equals(args.getString("mode",""));checkpointSeed=args.getString("seed","");start();}
 @Override public void onStart(){Bundle result=new Bundle();try{
  byte[] raw=MainActivity.read(new FileInputStream(new File(getTargetContext().getFilesDir(),"source.html")),ReplaySource.MAX_BYTES);
  String hash=MainActivity.sha(raw);
  if(!hash.equals("a711ebb3d142d03d8530926de9f4a795cee6b9e8cf87f777e9e41097b51c711e"))throw new IOException("not the explicitly requested replay");
  JSONObject test=new JSONObject().put("schema","royale-replay.skill-target-test.v1").put("source_sha256",hash)
   .put("targets",new JSONObject().put("18","golden-knight").put("24","boss-bandit"));
  if(freeCheckpoint)test=new JSONObject().put("schema","royale-replay.free-skill-checkpoint.v1").put("source_sha256",hash)
   .put("checkpoint_tick",2800).put("owner",1).put("tower_slot",1).put("minimum_exclusive",2417);
  if(freeCheckpoint&&!checkpointSeed.isEmpty())test.put("random_seed",Integer.parseInt(checkpointSeed));
  if(adaptiveSearch)test=new JSONObject().put("schema","royale-replay.adaptive-search-test.v1").put("source_sha256",hash);
  JSONObject job=NativePython.startPlayback(getTargetContext(),raw,4,"",false,test);
  File task=new File(job.getString("directory"));PlaybackService.openGame(getTargetContext());
  long deadline=android.os.SystemClock.elapsedRealtime()+3600000;
  while(android.os.SystemClock.elapsedRealtime()<deadline){
   Thread.sleep(1000);File stateFile=new File(task,"status.json");if(!stateFile.isFile())continue;
   JSONObject state=new JSONObject(MainActivity.text(stateFile,32768));
   if(state.optBoolean("monitor_active",true))continue;
   File proofFile=new File(task,adaptiveSearch?"adaptive-test-result.json":freeCheckpoint?"skill-checkpoint-result.json":"skill-target-result.json");
   if(!proofFile.isFile())throw new IOException(state.toString());
   JSONObject proof=new JSONObject(MainActivity.text(proofFile,1024*1024));
   if(!proof.optBoolean("simulation_test_completed",false)||proof.optBoolean("scene_published",true)||!hash.equals(proof.optString("source_sha256","")))throw new IOException("invalid simulation evidence");
   if(new File(task,"scene-v1-binding.json").exists())throw new IOException("simulation published an unexpected scene");
   result.putString("summary",proof.toString());result.putString("directory",task.getAbsolutePath());finish(-1,result);return;
  }throw new IOException("simulation timeout; original task retained");
 }catch(Throwable error){result.putString("error",error.toString());finish(0,result);}}
}
