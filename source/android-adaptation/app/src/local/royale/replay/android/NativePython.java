package local.royale.replay.android;

import android.content.Context;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import java.util.zip.*;
import org.json.JSONObject;

/** Isolated phone interpreter for the same full source parser as desktop. */
public final class NativePython {
    private static File installed;
    private static native int run(String home,String source,String destination)throws IOException;
    private static String fileHash(File file)throws Exception {
        MessageDigest digest=MessageDigest.getInstance("SHA-256");InputStream in=new FileInputStream(file);
        try{byte[] buffer=new byte[32768];int n;while((n=in.read(buffer))!=-1)digest.update(buffer,0,n);}finally{in.close();}
        StringBuilder hash=new StringBuilder();for(byte value:digest.digest())hash.append(String.format(Locale.ROOT,"%02x",value&255));return hash.toString();
    }
    private static File member(File root,String name)throws IOException {
        if(name.startsWith("/")||Arrays.asList(name.split("/")).contains(".."))throw new IOException("unsafe embedded runtime path");
        File file=new File(root,name);if(!file.getCanonicalPath().startsWith(root.getCanonicalPath()+File.separator))throw new IOException("runtime path leaves private directory");return file;
    }
    private static String assetHash(Context context,String name,int limit)throws Exception {
        MessageDigest digest=MessageDigest.getInstance("SHA-256");InputStream in=context.getAssets().open(name);long total=0;
        try{byte[] buffer=new byte[32768];int n;while((n=in.read(buffer))!=-1){total+=n;if(total>limit)throw new IOException("embedded archive exceeds limit");digest.update(buffer,0,n);}}finally{in.close();}
        StringBuilder result=new StringBuilder();for(byte value:digest.digest())result.append(String.format(Locale.ROOT,"%02x",value&255));return result.toString();
    }
    private static void verify(File root)throws Exception {
        JSONObject files=new JSONObject(MainActivity.text(new File(root,"runtime-files.json"),1024*1024));
        Iterator<String> keys=files.keys();int count=0;
        while(keys.hasNext()){String key=keys.next();if(++count>8192)throw new IOException("runtime manifest too large");
            if(!fileHash(member(root,key)).equals(files.getString(key)))throw new IOException("embedded runtime file differs: "+key);
        }
        if(count<10)throw new IOException("incomplete runtime manifest");
    }
    private static File unpack(Context context,String archiveName,String digestName,String prefix,int archiveLimit,long expandedLimit)throws Exception {
        String expected=new String(MainActivity.read(context.getAssets().open(digestName),256),StandardCharsets.US_ASCII).trim();
        if(!expected.matches("[a-f0-9]{64}"))throw new IOException("missing embedded runtime hash");
        File root=new File(context.getFilesDir(),prefix+expected.substring(0,16));
        if(root.exists()&&!new File(root,"runtime-files.json").isFile())RuntimeInstall.quarantineIncomplete(root);
        if(!root.exists()){
            if(!assetHash(context,archiveName,archiveLimit).equals(expected))throw new IOException("embedded archive hash differs");
            File staged=RuntimeInstall.createStaging(root);
            // Two streaming passes avoid holding an 85MB debugger archive and
            // its ByteArrayOutputStream copy in a phone's Java heap at once.
            ZipInputStream archive=new ZipInputStream(context.getAssets().open(archiveName));Set<String> seen=new HashSet<String>();long total=0;
            try{ZipEntry entry;while((entry=archive.getNextEntry())!=null){
                if(entry.isDirectory()||!seen.add(entry.getName())||seen.size()>8192)throw new IOException("invalid runtime member");
                File file=member(staged,entry.getName());File parent=file.getParentFile();if(!parent.isDirectory()&&!parent.mkdirs())throw new IOException("cannot create runtime folder");
                FileOutputStream out=new FileOutputStream(file);try{byte[] b=new byte[32768];int n;while((n=archive.read(b))!=-1){total+=n;if(total>expandedLimit)throw new IOException("runtime extraction budget exceeded");out.write(b,0,n);}out.getFD().sync();}finally{out.close();}
            }}finally{archive.close();}
            verify(staged);RuntimeInstall.publish(staged,root);return root;
        }
        verify(root);return root;
    }
    private static synchronized File ensure(Context context)throws Exception {
        if(installed!=null)return installed;
        File root=unpack(context,"python-runtime.zip","python-runtime.sha256","python-",128*1024*1024,384*1024*1024L);
        System.loadLibrary("replay_python");installed=root;return root;
    }
    static File sourceRuntime(Context context)throws Exception{return ensure(context);}
    static JSONObject parseUncached(Context context,byte[] source)throws Exception {
        File root=ensure(context);File jobs=new File(context.getFilesDir(),"local-imports");
        if(!jobs.isDirectory()&&!jobs.mkdir())throw new IOException("cannot create local import area");
        File folder=new File(jobs,UUID.randomUUID().toString());if(!folder.mkdir())throw new IOException("cannot reserve local import identity");
        File input=new File(folder,"input.html"),output=new File(folder,"result");MainActivity.write(input,source);
        if(hasNativeRuntime(root)){
            String command="LD_LIBRARY_PATH="+quoted(runtimeLibraries(context,root,null))+" "+quoted(runtimeExecutable(context,root).getAbsolutePath())
                +" import-source "+quoted(root.getAbsolutePath())+" "+quoted(input.getAbsolutePath())+" "+quoted(output.getAbsolutePath())+" -";
            StandaloneDoctor.Output process=StandaloneDoctor.root(command,90);
            if(process.code!=0)throw new IOException("完整 HTML 解析失败（"+process.code+"），本场未进入原生准备");
        }else run(root.getAbsolutePath(),input.getAbsolutePath(),output.getAbsolutePath());
        JSONObject result=new JSONObject(MainActivity.text(new File(output,"result.json"),32768));
        if(!result.optString("source_sha256","").equals(MainActivity.sha(source))||!result.optString("processing_location","").equals("android-embedded-python")||result.optBoolean("desktop_backend_used",true))throw new IOException("phone source result identity differs");
        result.put("private_source_manifest",new File(output,"source.json").getAbsolutePath());
        return result;
    }
    public static JSONObject importSource(Context context,byte[] source)throws Exception{
        JSONObject cached=SourcePreparation.prepare(context,source);
        // Only pure source data is reused. Every playback gets a new immutable
        // parent and fresh process/resource/code pins, simulation and JSON check.
        File jobs=new File(context.getFilesDir(),"local-imports"),folder=new File(jobs,UUID.randomUUID().toString());
        if(!folder.mkdir())throw new IOException("cannot reserve fresh source job");
        File result=new File(folder,"result");if(!result.mkdir())throw new IOException("cannot reserve source result");
        MainActivity.write(new File(folder,"input.html"),source);
        File original=new File(cached.getString("private_source_manifest"));
        MainActivity.write(new File(result,"source.json"),MainActivity.read(new FileInputStream(original),32*1024*1024));
        JSONObject report=new JSONObject(cached.toString());report.put("private_source_manifest",new File(result,"source.json").getAbsolutePath());
        MainActivity.write(new File(result,"result.json"),report.toString().getBytes(StandardCharsets.UTF_8));
        MainActivity.write(new File(context.getFilesDir(),"local-import-status.json"),report.toString().getBytes(StandardCharsets.UTF_8));
        return report;
    }
    private static String quoted(String path)throws IOException {
        if(path.indexOf('\0')>=0||path.indexOf('\n')>=0)throw new IOException("invalid local task argument");
        return "'"+path.replace("'","'\\''")+"'";
    }
    private static void checkClient(Context context,File apk)throws Exception {
        JSONObject report=StandaloneDoctor.compatibility(apk);
        android.content.pm.PackageInfo info=context.getPackageManager().getPackageInfo(StandaloneDoctor.GAME,0);
        report.put("client_version",info.versionName);
        if(!report.optBoolean("supported",false)){
            // Relocation is an automatic diagnostic stage, never an execution approval.
            InputStream reference=context.getAssets().open("client-relocation.tsv");
            try{
                ClientRelocator.Result found=ClientRelocator.scan(apk,reference,StandaloneDoctor.AUDITED_SHA);
                if(!found.libraryHash.equals(report.getString("library_sha256")))throw new IOException("检查期间游戏已更新，请重新检查");
                JSONObject anchors=new JSONObject();
                for(Map.Entry<String,List<Long>> item:found.candidates.entrySet()){
                    org.json.JSONArray locations=new org.json.JSONArray();for(Long va:item.getValue())locations.put(Long.toHexString(va));
                    anchors.put(item.getKey(),locations);
                }
                report.put("automatic_relocation_completed",true).put("unique_anchors",found.unique)
                    .put("ambiguous_anchors",found.ambiguous).put("missing_anchors",found.missing)
                    .put("reference_checks",found.referenceChecks).put("reference_candidates_rejected",found.referenceRejected)
                    .put("candidate_locations",anchors).put("object_layout_verified",false).put("native_execution_allowed",false);
                report.put("message","游戏更新后已自动定位 "+found.unique+"/"+found.candidates.size()+" 处调用候选；另有 "+found.ambiguous+" 处歧义、"+found.missing+" 处待定位。对象布局尚未验证，暂不能播放；原回放保留。");
            }finally{reference.close();}
        }
        MainActivity.write(new File(context.getFilesDir(),"client-compatibility.json"),report.toString().getBytes(StandardCharsets.UTF_8));
        if(!report.optBoolean("supported",false))throw new IOException(report.getString("message")+" 当前游戏："+info.versionName);
    }
    private static boolean hasNativeRuntime(File root){return new File(root,"app/mumu-support/runtime/manifest.json").isFile();}
    private static File runtimeExecutable(Context context,File root)throws Exception{
        if(hasNativeRuntime(root)){
            File executable=new File(root,"app/mumu-support/runtime/bin/phone_runtime");
            if(!executable.isFile()||!executable.canExecute())throw new IOException("native Android runtime unavailable");
            return executable;
        }
        return new File(context.getPackageManager().getApplicationInfo("local.royale.replay.android",0).nativeLibraryDir,"libphone_runtime.so");
    }
    private static String runtimeLibraries(Context context,File root,File prefix)throws Exception{
        if(hasNativeRuntime(root))return new File(root,"app/mumu-support/runtime/lib").getAbsolutePath()+":"+new File(root,"app/mumu-support/compiler/lib").getAbsolutePath();
        return (prefix==null?"":new File(prefix,"lib").getAbsolutePath()+":")+context.getPackageManager().getApplicationInfo("local.royale.replay.android",0).nativeLibraryDir;
    }
    public static JSONObject prepareSource(Context context,byte[] source)throws Exception {
        File root=ensure(context);
        String apk=context.getPackageManager().getApplicationInfo(StandaloneDoctor.GAME,0).sourceDir;
        if(!StandaloneDoctor.AUDITED_SHA.equals(StandaloneDoctor.libraryHash(new File(apk))))throw new IOException("客户端版本不匹配；未请求原生资源读取");
        JSONObject imported=importSource(context,source);
        File manifest=new File(imported.getString("private_source_manifest"));
        File output=new File(manifest.getParentFile(),"native-preparation");
        File executable=runtimeExecutable(context,root);
        if(!executable.isFile())throw new IOException("APK 未包含手机本地准备器");
        // This command can run only our own fixed-purpose packaged executable.
        // It accepts no shell command, Python snippet, network or memory address.
        String command="LD_LIBRARY_PATH="+quoted(runtimeLibraries(context,root,null))+" "+quoted(executable.getAbsolutePath())+" prepare "+quoted(root.getAbsolutePath())+" "+quoted(manifest.getAbsolutePath())+" "+quoted(output.getAbsolutePath())+" "+quoted(apk);
        StandaloneDoctor.Output process=StandaloneDoctor.root(command,90);
        MainActivity.write(new File(context.getFilesDir(),"local-preparation-process.json"),new JSONObject().put("exit",process.code).put("detail",process.text).toString().getBytes(StandardCharsets.UTF_8));
        if(process.code!=0)throw new IOException("手机本地准备未完成（"+process.code+"）；失败记录已保留，不自动重试");
        JSONObject report=new JSONObject(MainActivity.text(new File(output,"result.json"),32768));
        if(!report.optString("source_sha256","").equals(MainActivity.sha(source))||report.optBoolean("desktop_backend_used",true)
           ||report.optBoolean("native_calls",true)||report.optLong("retained_events",0)!=imported.optLong("retained_events",-1))throw new IOException("手机准备结果与源文件不一致");
        MainActivity.write(new File(context.getFilesDir(),"local-preparation-status.json"),report.toString().getBytes(StandardCharsets.UTF_8));
        report.put("private_preparation_directory",output.getAbsolutePath());
        return report;
    }
    private static File tools(Context context)throws Exception {
        File prefix=unpack(context,"android-tools.zip","android-tools.sha256","android-tools-",160*1024*1024,640*1024*1024L);
        for(String name:new String[]{"clang","clang++","ld.lld","lldb-server"})if(!new File(prefix,"bin/"+name).setExecutable(true,true))throw new IOException("cannot prepare own packaged tool: "+name);
        return prefix;
    }
    public static JSONObject buildSource(Context context,byte[] source)throws Exception {
        File root=ensure(context),prefix=tools(context);
        JSONObject prepared=prepareSource(context,source);
        File directory=new File(prepared.getString("private_preparation_directory"));
        File output=new File(directory,"native-build");
        String lib=context.getPackageManager().getApplicationInfo("local.royale.replay.android",0).nativeLibraryDir;
        File executable=runtimeExecutable(context,root);
        String command="LD_LIBRARY_PATH="+quoted(runtimeLibraries(context,root,prefix))+" "+quoted(executable.getAbsolutePath())
            +" build-component "+quoted(root.getAbsolutePath())+" "+quoted(new File(directory,"preparation.json").getAbsolutePath())+" "+quoted(output.getAbsolutePath())+" "+quoted(prefix.getAbsolutePath());
        StandaloneDoctor.Output process=StandaloneDoctor.root(command,90);
        MainActivity.write(new File(directory,"build-process.json"),new JSONObject().put("exit",process.code).put("detail",process.text).toString().getBytes(StandardCharsets.UTF_8));
        if(process.code!=0)throw new IOException("手机回放组件编译未完成（"+process.code+"）；未加载游戏，记录已保留");
        JSONObject report=new JSONObject(MainActivity.text(new File(output,"result.json"),32768));
        if(!report.optString("source_sha256","").equals(MainActivity.sha(source))||!report.optBoolean("compiled_on_phone",false)
           ||report.optBoolean("component_loaded",true)||report.optLong("retained_events",-1)!=prepared.optLong("retained_events",0))throw new IOException("手机组件编译回执不匹配");
        MainActivity.write(new File(context.getFilesDir(),"local-build-status.json"),report.toString().getBytes(StandardCharsets.UTF_8));
        return report;
    }
    public static synchronized JSONObject checkTools(Context context)throws Exception {
        File root=ensure(context),prefix=tools(context);
        File jobs=new File(context.getFilesDir(),"tool-checks");if(!jobs.isDirectory()&&!jobs.mkdir())throw new IOException("cannot reserve private tool checks");
        File task=new File(jobs,UUID.randomUUID().toString());if(!task.mkdir())throw new IOException("cannot reserve immutable tool check");
        File output=new File(task,"tools-check");
        String lib=context.getPackageManager().getApplicationInfo("local.royale.replay.android",0).nativeLibraryDir;
        File executable=runtimeExecutable(context,root);
        String command="LD_LIBRARY_PATH="+quoted(runtimeLibraries(context,root,prefix))+" "+quoted(executable.getAbsolutePath())
            +(hasNativeRuntime(root)?" check-native-tools ":" check-tools ")+quoted(root.getAbsolutePath())+" "+quoted(prefix.getAbsolutePath())+" "+quoted(output.getAbsolutePath())+" -";
        StandaloneDoctor.Output process=StandaloneDoctor.root(command,90);
        MainActivity.write(new File(task,"process.json"),new JSONObject().put("exit",process.code).put("detail",process.text).toString().getBytes(StandardCharsets.UTF_8));
        if(process.code!=0)throw new IOException("手机调试工具自检未通过（"+process.code+"）；未附加游戏，记录已保留");
        JSONObject report=new JSONObject(MainActivity.text(new File(output,"result.json"),32768));
        if(!report.optBoolean("debugger_loaded",false)||report.optBoolean("game_attached",true)||report.optLong("targets",-1)!=0)throw new IOException("invalid empty debugger self-check result");
        MainActivity.write(new File(context.getFilesDir(),"local-tools-status.json"),report.toString().getBytes(StandardCharsets.UTF_8));
        return report;
    }
    public static JSONObject startPlayback(Context context,byte[] source,double speed)throws Exception {
        return startPlayback(context,source,speed,"");
    }
    public static JSONObject startPlayback(Context context,byte[] source,double speed,String diagnostic)throws Exception {
        return startPlayback(context,source,speed,diagnostic,false);
    }
    public static JSONObject startPlayback(Context context,byte[] source,double speed,String diagnostic,boolean prepareAhead)throws Exception {
        return startPlayback(context,source,speed,diagnostic,prepareAhead,null);
    }
    static JSONObject startPlayback(Context context,byte[] source,double speed,String diagnostic,boolean prepareAhead,JSONObject skillTest)throws Exception {
        if(ReplayReset.blocked(context))throw new IOException("正在重置回放进程；完成后再播放");
        if(speed!=.25&&speed!=.5&&speed!=1&&speed!=2&&speed!=4)throw new IOException("无效倍速");
        File active=new File(context.getFilesDir(),"phone-active.json");
        if(active.isFile()&&!PlaybackStatus.launchFailureReleased(context)){
            JSONObject previous=new JSONObject(MainActivity.text(active,8192));
            File directory=PlaybackStatus.activeDirectory(context);
            File status=new File(directory,"status.json");
            JSONObject prior=status.isFile()?new JSONObject(MainActivity.text(status,32768)):new JSONObject();
            String state=prior.optString("state","queued");
            boolean ended=state.equals("stopped")||PlaybackStatus.preparationReleased(context,directory);
            if(state.equals("complete")&&sceneReleased(directory,prior))ended=true;
            if(state.equals("failed_recovered")){
                JSONObject recovery=new JSONObject(MainActivity.text(new File(directory,"failure-recovery.json"),8192));
                String outcome=recovery.optString("result","");
                ended=(outcome.equals("already_clean")||outcome.equals("already_released")||outcome.equals("restarted"))
                    &&prior.optLong("game_pid",0)>0&&prior.optLong("game_pid",0)==recovery.optLong("game_pid",-1)
                    &&prior.optString("game_start_time","").equals(recovery.optString("game_start_time","missing"))
                    &&previous.optString("source_sha256","").equals(recovery.optString("source_sha256","missing"));
            }
            if(!ended&&preparationCandidate(prior)){
                releasePreparation(context,directory);
                ended=PlaybackStatus.preparationReleased(context,directory);
            }
            if(!ended&&prior.optLong("game_pid",0)>0)ended=gameGenerationReleased(prior);
            if(!ended)throw new IOException("旧回放现场尚未释放（"+state+"）。请仅重启游戏客户端，进入大厅后重新选择 HTML；历史记录保留，未重复提交，也不会自动跳转。");
        }
        File root=ensure(context),prefix=tools(context);
        String apk=context.getPackageManager().getApplicationInfo(StandaloneDoctor.GAME,0).sourceDir;
        checkClient(context,new File(apk));
        JSONObject imported=importSource(context,source);
        File manifest=new File(imported.getString("private_source_manifest"));
        File directory=new File(manifest.getParentFile(),"phone-playback");
        File request=new File(manifest.getParentFile(),"play-request.json");
        JSONObject requested=new JSONObject().put("source_manifest",manifest.getAbsolutePath()).put("source_sha256",MainActivity.sha(source)).put("apk",apk).put("speed",speed).put("prepare_ahead",prepareAhead);
        if(skillTest!=null){
            String schema=skillTest.optString("schema","");
            if((!"royale-replay.skill-target-test.v1".equals(schema)&&!"royale-replay.free-skill-checkpoint.v1".equals(schema)&&!"royale-replay.adaptive-search-test.v1".equals(schema)&&!"royale-replay.seed-locked-playback.v1".equals(schema))||!MainActivity.sha(source).equals(skillTest.optString("source_sha256","")))throw new IOException("技能预演或固定种子播放来源不一致");
            requested.put("royale-replay.seed-locked-playback.v1".equals(schema)?"seed_locked_playback":"skill_target_test",new JSONObject(skillTest.toString()));
        }
        if(!diagnostic.isEmpty()){
            File evidence=new File(diagnostic);File queue=new File(context.getFilesDir(),"replay-queue");
            if(!evidence.getCanonicalFile().getParentFile().equals(queue.getCanonicalFile())||!evidence.getName().matches("[a-f0-9-]{36}\\.diagnostic\\.json"))throw new IOException("诊断文件必须来自本机队列");
            byte[] raw=MainActivity.read(new FileInputStream(evidence),4*1024*1024);
            JSONObject proof=new JSONObject(new String(raw,StandardCharsets.UTF_8));
            if(!proof.optBoolean("user_authorized",false)||!MainActivity.sha(source).equals(proof.optString("source_sha256","")))throw new IOException("诊断源或授权不一致");
            requested.put("diagnostic_prefix",evidence.getCanonicalPath()).put("diagnostic_sha256",MainActivity.sha(raw));
        }
        MainActivity.write(request,requested.toString().getBytes(StandardCharsets.UTF_8));
        JSONObject job=new JSONObject().put("directory",directory.getAbsolutePath()).put("source_sha256",MainActivity.sha(source));
        MainActivity.write(active,job.toString().getBytes(StandardCharsets.UTF_8));
        String lib=context.getPackageManager().getApplicationInfo("local.royale.replay.android",0).nativeLibraryDir;
        File executable=runtimeExecutable(context,root);
        String command="LD_LIBRARY_PATH="+quoted(runtimeLibraries(context,root,prefix))+" "+quoted(executable.getAbsolutePath())
            +" play "+quoted(root.getAbsolutePath())+" "+quoted(request.getAbsolutePath())+" "+quoted(directory.getAbsolutePath())+" "+quoted(prefix.getAbsolutePath());
        // Device-local root child, file-backed output, no computer/ADB service.
        // It continues while the native game is foreground; never destroy a
        // published task merely because this Activity closes or is reclaimed.
        Process process=new ProcessBuilder("su","-c",command).redirectErrorStream(true)
            .redirectOutput(new File(manifest.getParentFile(),"play-process.log")).start();
        process.getOutputStream().close();
        File status=new File(directory,"status.json");long deadline=System.currentTimeMillis()+25000;
        while(!status.isFile()&&System.currentTimeMillis()<deadline){
            if(process.waitFor(200,java.util.concurrent.TimeUnit.MILLISECONDS)){
                // No output directory means the fixed CLI never entered Python
                // and cannot have published any native task. Preserve metadata.
                if(!directory.exists()){
                    job.put("launch_failed_before_native_entry",true);
                    MainActivity.write(active,job.toString().getBytes(StandardCharsets.UTF_8));
                }
                String detail="";
                try{detail=MainActivity.text(new File(manifest.getParentFile(),"play-process.log"),16384).trim();if(detail.length()>600)detail=detail.substring(detail.length()-600);}catch(IOException ignored){}
                throw new IOException("本机执行器启动失败（"+process.exitValue()+"），启动记录已保留"+(detail.isEmpty()?"":"："+detail));
            }
        }
        if(!status.isFile())throw new IOException("本机执行器尚未确认启动；保留请求，不自动重试");
        return job;
    }
    static JSONObject resetProcesses(Context context,File request,File output)throws Exception{
        File home=ensure(context),prefix=tools(context);
        String command="LD_LIBRARY_PATH="+quoted(runtimeLibraries(context,home,prefix))+" "+quoted(runtimeExecutable(context,home).getAbsolutePath())
            +" reset "+quoted(home.getAbsolutePath())+" "+quoted(request.getAbsolutePath())+" "+quoted(output.getAbsolutePath())+" "+quoted(prefix.getAbsolutePath());
        StandaloneDoctor.Output result=StandaloneDoctor.root(command,120);
        MainActivity.write(new File(request.getParentFile(),"process-output.txt"),result.text.getBytes(StandardCharsets.UTF_8));
        if(result.code!=0)throw new IOException("未能重置全部占用："+result.text.substring(Math.max(0,result.text.length()-500))+"；没有重发回放任务，请查看诊断记录");
        return new JSONObject(MainActivity.text(new File(output,"result.json"),32768));
    }
    static JSONObject currentGameGeneration()throws Exception{
        StandaloneDoctor.Output pid=StandaloneDoctor.root("pidof "+StandaloneDoctor.GAME);
        if(pid.code!=0||!pid.text.matches("[1-9][0-9]{0,6}"))throw new IOException("无法确认唯一游戏进程；不释放旧现场");
        StandaloneDoctor.Output stat=StandaloneDoctor.root("cat /proc/"+pid.text+"/stat");
        int close=stat.text.lastIndexOf(')');
        if(stat.code!=0||close<0)throw new IOException("无法确认游戏进程代际");
        String[] fields=stat.text.substring(close+1).trim().split("\\s+");
        if(fields.length<=19||!fields[19].matches("[0-9]+"))throw new IOException("无效的游戏进程代际");
        StandaloneDoctor.Output after=StandaloneDoctor.root("pidof "+StandaloneDoctor.GAME);
        if(after.code!=0||!after.text.equals(pid.text))throw new IOException("游戏进程正在变化");
        return new JSONObject().put("game_pid",Long.parseLong(pid.text)).put("game_start_time",fields[19]);
    }
    static boolean generationChanged(JSONObject prior,JSONObject current){
        return prior.optLong("game_pid",0)>0&&current.optLong("game_pid",0)>0
            &&(prior.optLong("game_pid",0)!=current.optLong("game_pid",0)
               ||(!prior.optString("game_start_time","").isEmpty()&&!current.optString("game_start_time","").isEmpty()
                   &&!prior.optString("game_start_time","").equals(current.optString("game_start_time",""))));
    }
    static boolean sameGameGeneration(JSONObject expected)throws Exception{
        JSONObject current=currentGameGeneration();
        return expected.optLong("game_pid",0)==current.optLong("game_pid",-1)
            &&!expected.optString("game_start_time","").isEmpty()
            &&expected.optString("game_start_time","").equals(current.optString("game_start_time",""));
    }
    static boolean releasedStat(JSONObject expected,int code,String value)throws Exception{
        long pid=expected.optLong("game_pid",0);String start=expected.optString("game_start_time","");
        if(pid<=0||pid>=(1<<22)||!start.matches("[0-9]+"))throw new IOException("缺少旧游戏进程身份；不清理现场");
        if(code!=0)throw new IOException("游戏进程检查未通过；不把权限错误当作退出");
        if(value.equals("REPLAY_PROCESS_ABSENT"))return true;
        return !StandaloneDoctor.startTime(new StandaloneDoctor.Output(code,value)).equals(start);
    }
    static boolean gameGenerationReleased(JSONObject expected)throws Exception{
        long pid=expected.optLong("game_pid",0);
        if(pid<=0||pid>=(1<<22))throw new IOException("无效旧游戏进程");
        String path="/proc/"+pid;
        StandaloneDoctor.Output value=StandaloneDoctor.root("if test -d "+path+"; then cat "+path+"/stat; else printf REPLAY_PROCESS_ABSENT; fi",5);
        return releasedStat(expected,value.code,value.text);
    }
    static void recordRelease(Context context,JSONObject expected)throws Exception{
        File directory=PlaybackStatus.activeDirectory(context);
        JSONObject current=new JSONObject(MainActivity.text(new File(directory,"status.json"),32768));
        if(current.optLong("game_pid",0)!=expected.optLong("game_pid",-1)||!current.optString("game_start_time","").equals(expected.optString("game_start_time","missing")))return;
        JSONObject release=new JSONObject().put("game_pid",expected.optLong("game_pid",0)).put("game_start_time",expected.getString("game_start_time"))
            .put("generation_released",true).put("updated_at",System.currentTimeMillis()/1000);
        MainActivity.write(new File(directory,"process-release.json"),release.toString().getBytes(StandardCharsets.UTF_8));
    }
    static void reconcileReleased(Context context,JSONObject expected)throws Exception{
        if(expected.optString("state","").equals("complete")&&!expected.optBoolean("monitor_active",true)
                &&PlaybackStatus.completedVerified(PlaybackStatus.activeDirectory(context),expected))return;
        if(preparationCandidate(expected)){
            File directory=PlaybackStatus.activeDirectory(context);
            if(!PlaybackStatus.preparationReleased(context,directory))releasePreparation(context,directory);
            return;
        }
        if(expected.optLong("game_pid",0)>0&&gameGenerationReleased(expected))recordRelease(context,expected);
    }
    static boolean preparationCandidate(JSONObject state){
        String phase=state.optString("state","");
        return (phase.equals("needs_review")||phase.equals("failed_before_native")||phase.equals("cancelled"))
            &&(!state.optBoolean("native_entry_started",true)||(phase.equals("needs_review")&&state.optLong("game_pid",0)==0));
    }
    private static synchronized void releasePreparation(Context context,File directory)throws Exception{
        File root=ensure(context),prefix=tools(context),action=new File(directory,UUID.randomUUID().toString());
        if(!action.mkdir())throw new IOException("无法保存准备失败的核验记录");
        String lib=context.getPackageManager().getApplicationInfo("local.royale.replay.android",0).nativeLibraryDir;
        String command="LD_LIBRARY_PATH="+quoted(runtimeLibraries(context,root,prefix))+" "+quoted(runtimeExecutable(context,root).getAbsolutePath())
            +" release-preparation "+quoted(root.getAbsolutePath())+" "+quoted(directory.getAbsolutePath())+" "+quoted(new File(action,"preparation-release").getAbsolutePath())+" "+quoted(prefix.getAbsolutePath());
        StandaloneDoctor.Output result=StandaloneDoctor.root(command,30);
        MainActivity.write(new File(action,"process-output.txt"),result.text.getBytes(StandardCharsets.UTF_8));
        if(result.code!=0){
            String[] lines=result.text.trim().split("\\n");String reason=lines.length>0?lines[lines.length-1]:"无执行器输出";
            if(reason.length()>240)reason=reason.substring(reason.length()-240);
            throw new IOException("准备失败现场未能安全核验（"+result.code+"）："+reason+"；诊断记录保留，未修改游戏");
        }
    }
    private static void confirmTerminalChoice(File directory,JSONObject state)throws Exception{
        JSONObject choice=new JSONObject().put("terminal_choice_confirmed",true).put("game_pid",state.getLong("game_pid"))
            .put("game_start_time",state.getString("game_start_time")).put("source_sha256",state.getString("source_sha256"));
        MainActivity.write(new File(directory,"terminal-choice.json"),choice.toString().getBytes(StandardCharsets.UTF_8));
    }
    static synchronized void finishCompleted(Context context,JSONObject expected)throws Exception{
        if(PlaybackService.isBusy())throw new IOException("正在收尾，请稍后再点重放或退出");
        File directory=PlaybackStatus.activeDirectory(context);
        JSONObject state=PlaybackStatus.read(context);
        if(!state.optString("state","").equals("complete")||!PlaybackStatus.completedVerified(directory,state)
           ||state.optLong("game_pid",0)!=expected.optLong("game_pid",-1)||!state.optString("game_start_time","").equals(expected.optString("game_start_time","missing")))throw new IOException("终局身份已变化，未操作游戏");
        if(sceneReleased(directory,state)){confirmTerminalChoice(directory,state);return;}
        if(gameGenerationReleased(state)){recordRelease(context,state);confirmTerminalChoice(directory,state);return;}
        File root=ensure(context),prefix=tools(context),action=new File(directory,UUID.randomUUID().toString());
        if(!action.mkdir())throw new IOException("无法保存本次退出操作");
        File output=new File(action,"phone-finish");
        String lib=context.getPackageManager().getApplicationInfo("local.royale.replay.android",0).nativeLibraryDir;
        String command="LD_LIBRARY_PATH="+quoted(runtimeLibraries(context,root,prefix))+" "+quoted(runtimeExecutable(context,root).getAbsolutePath())
            +" finish "+quoted(root.getAbsolutePath())+" "+quoted(new File(directory,"scene-v1-binding.json").getAbsolutePath())+" "+quoted(output.getAbsolutePath())+" "+quoted(prefix.getAbsolutePath());
        StandaloneDoctor.Output result=StandaloneDoctor.root(command,45);
        MainActivity.write(new File(action,"process-output.txt"),result.text.getBytes(StandardCharsets.UTF_8));
        if(result.code!=0)throw new IOException("安全退出未完成，已保留现场；不会重复提交（"+result.code+"）");
        if(!gameGenerationReleased(state))throw new IOException("游戏旧进程仍在，未解除占用");
        recordRelease(context,state);confirmTerminalChoice(directory,state);
    }
    static boolean sceneReleased(File directory,JSONObject state)throws Exception{
        File proof=new File(directory,"lobby-release.json");if(!proof.isFile())return false;
        JSONObject release=new JSONObject(MainActivity.text(proof,8192));
        JSONObject cleanup=new JSONObject(MainActivity.text(new File(directory,"scene-v1-cleanup-v1-result.json"),128*1024));
        return release.optBoolean("scene_released",false)&&release.optLong("game_pid",0)==state.optLong("game_pid",-1)
            &&release.optString("game_start_time","").equals(state.optString("game_start_time","missing"))
            &&release.optString("source_sha256","").equals(state.optString("source_sha256","missing"))
            &&cleanup.optBoolean("component_unloaded",false)&&cleanup.optBoolean("detached",false)&&"[]".equals(cleanup.optString("errors","missing"));
    }
    public static synchronized JSONObject recoverInitialization(Context context)throws Exception {
        File root=ensure(context),prefix=tools(context);
        JSONObject active=new JSONObject(MainActivity.text(new File(context.getFilesDir(),"phone-active.json"),8192));
        File directory=new File(active.getString("directory"));
        if(!directory.getCanonicalPath().startsWith(new File(context.getFilesDir(),"local-imports").getCanonicalPath()+File.separator))throw new IOException("不属于本控制台");
        File output=new File(directory,"phone-recovery");
        String lib=context.getPackageManager().getApplicationInfo("local.royale.replay.android",0).nativeLibraryDir;
        String command="LD_LIBRARY_PATH="+quoted(runtimeLibraries(context,root,prefix))+" "+quoted(runtimeExecutable(context,root).getAbsolutePath())
            +" recover "+quoted(root.getAbsolutePath())+" "+quoted(new File(directory,"bootstrap-v2-binding.json").getAbsolutePath())+" "+quoted(output.getAbsolutePath())+" "+quoted(prefix.getAbsolutePath());
        StandaloneDoctor.Output process=StandaloneDoctor.root(command,90);
        if(process.code!=0)throw new IOException("原初始化观察未通过（"+process.code+"），未重复发布；保留现场");
        return new JSONObject(MainActivity.text(new File(output,"result.json"),8192));
    }
    private NativePython(){}
}
