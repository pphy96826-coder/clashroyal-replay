package local.royale.replay.android;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.security.MessageDigest;
import java.util.*;
import java.util.zip.*;

/** Bounded, click-scoped export of our own records. No root, game or network API. */
public final class DiagnosticExport {
    static final String VERSION="2026.10.23-mumu-hotfix70-port";
    private static final int MAX_FILE=4*1024*1024,MAX_TOTAL=16*1024*1024,MAX_FILES=256;
    private static final Set<String> GLOBAL=new HashSet<String>(Arrays.asList(
        "client-compatibility.json","phone-active.json","phone-service-state.json","local-import-status.json",
        "playback-service-startup.jsonl","playback-service-startup.previous.jsonl",
        "local-preparation-status.json","local-preparation-process.json","local-build-status.json","local-tools-status.json"));
    private static final Set<String> TASK=new HashSet<String>(Arrays.asList(
        "status.json","error.txt","native-entry.json","ability-search.json","failure-recovery.json",
        "preparation-release.json","process-release.json","automatic-return.json","maps-diagnostic.json",
        "preparation-hint.json","seed-search.json","terminal-choice.json",
        "prediction-process.jsonl","matching-source.json","page-comparison.json","skill-candidate-pool.json"));
    private DiagnosticExport(){}

    static File checkedTask(File files,File active)throws IOException{
        return PrivateTaskPaths.resolve(files,active,true);
    }
    static boolean taskName(String name){
        return TASK.contains(name)||name.matches("[a-z0-9][a-z0-9-]{0,95}-(result|binding|component|source-execution|timing)\\.json");
    }
    private static void collect(File files,File task,SortedMap<String,File> selected)throws IOException{
        for(String name:GLOBAL)selected.put("console/"+name,new File(files,name));
        if(task==null)return;
        for(String name:new String[]{"play-process.log","play-request.json","source.json","result.json"})
            selected.put("startup/"+name,new File(task.getParentFile(),name));
        if(PrivateTaskPaths.missing(task))return;
        File[] children=task.listFiles();if(children==null)throw new IOException("task directory unavailable");
        if(children.length>4096)throw new IOException("task directory exceeds enumeration limit");
        for(File file:children)if(taskName(file.getName()))selected.put("task/"+file.getName(),file);
        File preparation=new File(task,"native-preparation");
        for(String name:new String[]{"result.json","observation.json","levels.json","towers.json","preparation.json","preparation-delayed.json","maps-read-diagnostic.json","catalog-update-diagnostic.json","tower-update-diagnostic.json"})
            selected.put("task/native-preparation/"+name,new File(preparation,name));
        // Calibration is bounded to 12 attempts by the runtime, not a recursive scan.
        for(int i=0;i<12;i++)selected.put("task/native-preparation/preparation-calibrated-"+i+".json",new File(preparation,"preparation-calibrated-"+i+".json"));
        for(String name:new String[]{"loader-diagnostic.json","loader-profile.json","runtime-observation.json"})
            selected.put("task/native-preparation/runtime/"+name,new File(preparation,"runtime/"+name));
    }
    private static byte[] snapshot(File root,File file)throws IOException{
        Path base=root.toPath().toAbsolutePath().normalize(),path=file.toPath().toAbsolutePath().normalize();
        if(!path.startsWith(base))throw new IOException("outside private files");
        Path cursor=base;
        for(Path part:base.relativize(path)){cursor=cursor.resolve(part);if(Files.isSymbolicLink(cursor))throw new IOException("linked record refused");}
        BasicFileAttributes before=Files.readAttributes(path,BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS);
        if(!before.isRegularFile()||before.size()>MAX_FILE)throw new IOException("nonregular or oversized record");
        ByteArrayOutputStream bytes=new ByteArrayOutputStream();
        try(InputStream input=Files.newInputStream(path,LinkOption.NOFOLLOW_LINKS)){
            byte[] buffer=new byte[16384];int n;
            while((n=input.read(buffer))!=-1){if(bytes.size()+n>MAX_FILE)throw new IOException("record grew beyond limit");bytes.write(buffer,0,n);}
        }
        BasicFileAttributes after=Files.readAttributes(path,BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS);
        if(before.size()!=after.size()||bytes.size()!=before.size()||!before.lastModifiedTime().equals(after.lastModifiedTime())
           ||!Objects.equals(before.fileKey(),after.fileKey()))throw new IOException("record changed during export");
        return bytes.toByteArray();
    }
    private static String sha(byte[] bytes)throws Exception{
        StringBuilder text=new StringBuilder();for(byte value:MessageDigest.getInstance("SHA-256").digest(bytes))text.append(String.format(Locale.ROOT,"%02x",value&255));return text.toString();
    }
    private static void entry(ZipOutputStream zip,String name,byte[] bytes)throws IOException{
        zip.putNextEntry(new ZipEntry(name));zip.write(bytes);zip.closeEntry();
    }
    /** The caller supplies ONLY a system-picker output stream and the current task. */
    static int write(File files,File active,OutputStream destination,String environment)throws Exception{
        SortedMap<String,File> selected=new TreeMap<String,File>();
        StringBuilder report=new StringBuilder("Royale replay diagnostic export v1\nConsole: "+VERSION+"\n"+environment+"\n");
        report.append("Contains private paths, process addresses and replay command records. Share privately.\n")
              .append("No raw HTML, APK/SO, browser data, cookies, signing keys or queue contents are collected.\n")
              .append("Read-only snapshots, not an atomic checkpoint. Export does not stop/retry/clean a replay.\n");
        File task=null;
        if(active!=null)try{task=checkedTask(files,active);report.append("Task: "+task.getParentFile().getParentFile().getName()+"\n");}
        catch(IOException error){report.append("Active task rejected: "+error.getMessage()+"\n");}
        else report.append("No readable active task; console records only.\n");
        collect(files,task,selected);
        SortedMap<String,byte[]> snapshots=new TreeMap<String,byte[]>();int total=0;
        for(Map.Entry<String,File> record:selected.entrySet()){
            if(!Files.exists(record.getValue().toPath(),LinkOption.NOFOLLOW_LINKS))continue;
            try{
                if(snapshots.size()>=MAX_FILES)throw new IOException("file count limit reached");
                if(record.getValue().length()>MAX_TOTAL-total)throw new IOException("total byte limit reached");
                byte[] bytes=snapshot(files,record.getValue());
                if(bytes.length>MAX_TOTAL-total)throw new IOException("total byte limit reached");
                snapshots.put(record.getKey(),bytes);total+=bytes.length;
            }catch(IOException error){report.append("Skipped "+record.getKey()+": "+error.getMessage()+"\n");}
        }
        StringBuilder checks=new StringBuilder();
        try(ZipOutputStream zip=new ZipOutputStream(destination)){
            for(Map.Entry<String,byte[]> record:snapshots.entrySet()){
                entry(zip,record.getKey(),record.getValue());checks.append(sha(record.getValue())+"  "+record.getKey()+"\n");
            }
            report.append("Records: "+snapshots.size()+"; uncompressed bytes: "+total+"\n");
            entry(zip,"REPORT.txt",report.toString().getBytes(StandardCharsets.UTF_8));
            entry(zip,"SHA256SUMS.txt",checks.toString().getBytes(StandardCharsets.UTF_8));
        }
        return snapshots.size();
    }
}
