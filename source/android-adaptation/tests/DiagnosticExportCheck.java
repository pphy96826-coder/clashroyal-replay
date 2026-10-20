package local.royale.replay.android;
import java.io.*;
public final class DiagnosticExportCheck {
    public static void main(String[] args)throws Exception{
        try(OutputStream output=new FileOutputStream(args[2])){
            System.out.println(DiagnosticExport.write(new File(args[0]),args[1].equals("none")?null:new File(args[1]),output,"Android SDK: 30; ABIs: [arm64-v8a]"));
        }
    }
}
