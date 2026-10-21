package local.royale.replay.android;
import java.io.*;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;

/** Bind aliases by file identity; an absent leaf never proves a process exit. */
public final class PrivateTaskPaths {
    private PrivateTaskPaths(){}
    static boolean missing(File file)throws IOException{
        try{Files.readAttributes(file.toPath(),BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS);return false;}
        catch(NoSuchFileException absent){return true;}
    }
    static File resolve(File files,File stored,boolean allowMissing)throws IOException{
        File result=stored.getParentFile(),job=result==null?null:result.getParentFile(),imports=job==null?null:job.getParentFile();
        if(!stored.isAbsolute()||!stored.getName().equals("phone-playback")||result==null||!result.getName().equals("result")
           ||job==null||!job.getName().matches("[a-f0-9-]{36}")||imports==null
           ||!Files.isSameFile(imports.toPath(),new File(files,"local-imports").toPath()))throw new IOException("任务路径不属于本控制台");
        for(File path=stored;;path=path.getParentFile()){
            if(Files.isSymbolicLink(path.toPath()))throw new IOException("linked task refused");
            if(path.equals(imports))break;
        }
        File expected=new File(files,"local-imports/"+job.getName()+"/result/phone-playback");
        if(!Files.isSameFile(result.toPath(),expected.getParentFile().toPath()))throw new IOException("任务父目录身份不一致");
        boolean first=missing(stored),second=missing(expected);
        if(first||second){if(!(allowMissing&&first&&second))throw new IOException("没有有效的本机任务");}
        else if(!Files.readAttributes(stored.toPath(),BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS).isDirectory()
                ||!Files.isSameFile(stored.toPath(),expected.toPath()))throw new IOException("任务目录身份不一致");
        return expected;
    }
    static boolean launchFailureProven(File directory,boolean failed,String activeHash,String requestHash,String sourceHash,File sourceManifest)throws IOException{
        if(!failed)return false;
        if(!activeHash.matches("[a-f0-9]{64}")||!activeHash.equals(requestHash)||!activeHash.equals(sourceHash))return false;
        // This flag is written ONLY after the child has exited and before its
        // Python task directory exists. Absence without the flag is unknown.
        if(!missing(directory))return false;
        File source=new File(directory.getParentFile(),"source.json"),request=new File(directory.getParentFile(),"play-request.json");
        for(File path:new File[]{source,request,sourceManifest}){
            if(Files.isSymbolicLink(path.toPath())||!Files.readAttributes(path.toPath(),BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS).isRegularFile())return false;
        }
        return Files.isSameFile(source.toPath(),sourceManifest.toPath());
    }
}
