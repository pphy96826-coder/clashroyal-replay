package local.royale.replay.android;
import java.io.*;
public final class DiagnosticExportCheck {
    public static void main(String[] args)throws Exception{
        if(args[0].equals("--proof")){
            File task=PrivateTaskPaths.resolve(new File(args[1]),new File(args[2]),true);
            System.out.println(PrivateTaskPaths.launchFailureProven(task,Boolean.parseBoolean(args[3]),args[4],args[5],args[6],new File(args[7])));return;
        }
        try(OutputStream output=new FileOutputStream(args[2])){
            System.out.println(DiagnosticExport.write(new File(args[0]),args[1].equals("none")?null:new File(args[1]),output,"Android SDK: 30; ABIs: [arm64-v8a]"));
        }
    }
}
