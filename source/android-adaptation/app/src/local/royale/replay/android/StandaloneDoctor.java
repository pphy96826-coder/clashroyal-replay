package local.royale.replay.android;

import java.io.*;
import java.security.MessageDigest;
import java.util.Locale;
import java.util.concurrent.TimeUnit;
import java.util.zip.ZipFile;
import java.util.zip.ZipEntry;
import org.json.JSONObject;

/** Read-only on-device capability check. Does not attach or publish a replay. */
public final class StandaloneDoctor {
    public static final String GAME="com.tencent.tmgp.supercell.clashroyale";
    public static final String AUDITED_SHA="c6b2482a2f1fbd2e15c99df7fb18ba3d5596b77b3a81930d3638241a3c37fe55";
    static final class Output {final int code;final String text;Output(int c,String t){code=c;text=t;}}
    static Output root(String fixedCommand)throws Exception {
        return root(fixedCommand,25);
    }
    static Output root(String fixedCommand,int seconds)throws Exception {
        final Process process=new ProcessBuilder("su","-c",fixedCommand).redirectErrorStream(true).start();
        final ByteArrayOutputStream bytes=new ByteArrayOutputStream();
        final IOException[] problem=new IOException[1];
        Thread collector=new Thread(new Runnable(){public void run(){try{InputStream in=process.getInputStream();byte[] b=new byte[2048];int n;while((n=in.read(b))!=-1){if(bytes.size()+n>16384)throw new IOException("root check output exceeds limit");bytes.write(b,0,n);}in.close();}catch(IOException e){problem[0]=e;}}});
        collector.setDaemon(true);collector.start();
        if(!process.waitFor(seconds,TimeUnit.SECONDS)){process.destroy();throw new IOException("本机任务等待超时；不自动重试，请检查保留的任务记录");}
        collector.join(1000);if(collector.isAlive())throw new IOException("root check pipe did not close");
        if(problem[0]!=null)throw problem[0];
        return new Output(process.exitValue(),bytes.toString("UTF-8").trim());
    }
    static String libraryHash(File apk)throws Exception {
        ZipFile zip=new ZipFile(apk);
        try{ZipEntry entry=zip.getEntry("lib/arm64-v8a/libg.so");
            if(entry==null||entry.getSize()!=30559184L)throw new IOException("客户端 ARM64 库大小不匹配，拒绝启用运行时");
            MessageDigest hash=MessageDigest.getInstance("SHA-256");InputStream in=zip.getInputStream(entry);long total=0;
            try{byte[] buffer=new byte[32768];int n;while((n=in.read(buffer))!=-1){total+=n;if(total>30559184L)throw new IOException("客户端库超出已审计大小");hash.update(buffer,0,n);}}finally{in.close();}
            if(total!=30559184L)throw new IOException("客户端库读取不完整");
            StringBuilder result=new StringBuilder();for(byte v:hash.digest())result.append(String.format(Locale.ROOT,"%02x",v&255));return result.toString();
        }finally{zip.close();}
    }
    public static JSONObject inspect(File apk)throws Exception {
        JSONObject report=new JSONObject().put("schema","royale-replay.android-standalone-doctor.v1")
            .put("check_execution_location","android").put("desktop_backend_used",false).put("native_calls",false).put("debugger_attached",false)
            .put("network_settings_changed",false).put("game_apk_changed",false).put("standalone_playback_ready",false);
        String hash=libraryHash(apk);boolean pinned=AUDITED_SHA.equals(hash);
        report.put("library_sha256",hash).put("audited_library_matches",pinned);
        if(!pinned)return report.put("message","客户端库不匹配，未请求 root 或执行原生操作");
        Output who=root("id -u");boolean rootReady=who.code==0&&who.text.equals("0");
        report.put("existing_root_granted",rootReady).put("root_check_exit",who.code);
        if(!rootReady)report.put("root_check_detail",who.text.substring(0,Math.min(240,who.text.length())));
        if(!rootReady)return report.put("message","控制台未获得设备已有 root 授权；没有尝试提权或绕过限制");
        Output pid=root("pidof "+GAME);
        if(pid.code!=0||!pid.text.matches("[1-9][0-9]{0,6}"))return report.put("game_running",false).put("message","请打开已安装的官服客户端；未附加任何进程");
        report.put("game_running",true);
        String path="/proc/"+pid.text;
        Output first=root("cat "+path+"/stat");String before=startTime(first);
        Output status=root("cat "+path+"/status");boolean untraced=false;
        if(status.code==0)for(String line:status.text.split("\\n"))if(line.startsWith("TracerPid:"))untraced=line.substring(10).trim().equals("0");
        Output memory=root("head -c 0 "+path+"/mem"); // open only; no game bytes are returned.
        Output after=root("cat "+path+"/stat");boolean stable=before.equals(startTime(after));
        report.put("game_generation_stable",stable).put("existing_debugger_absent",untraced).put("game_memory_open_allowed",memory.code==0);
        boolean permitted=stable&&untraced&&memory.code==0;
        return report.put("local_debug_prerequisites_passed",permitted).put("message",permitted?
            "本机版本和已有调试权限通过；独立执行器仍待接入，检查不等于播放成功。":
            "设备调试前提未通过；未修改权限、未附加或重试原生操作。");
    }
    static String startTime(Output stat)throws IOException {
        int close=stat.text.lastIndexOf(')');String[] fields=stat.text.substring(close+1).trim().split("\\s+");
        if(stat.code!=0||close<0||fields.length<=19||!fields[19].matches("[0-9]+"))throw new IOException("游戏进程身份读取失败");
        return fields[19];
    }
    private StandaloneDoctor(){}
}
