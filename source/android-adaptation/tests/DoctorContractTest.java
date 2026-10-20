package local.royale.replay.android;

import java.io.*;
import java.nio.file.*;
import java.util.zip.*;

/** Pure Java checks; never invokes su or touches a device. */
public final class DoctorContractTest {
    public static void main(String[] args)throws Exception {
        int tests=0;
        StringBuilder stat=new StringBuilder("123 (name with spaces) S");
        for(int i=1;i<19;i++)stat.append(" 0");stat.append(" 76543");
        if(!StandaloneDoctor.startTime(new StandaloneDoctor.Output(0,stat.toString())).equals("76543"))throw new AssertionError("starttime index mismatch");tests++;
        for(StandaloneDoctor.Output output:new StandaloneDoctor.Output[]{new StandaloneDoctor.Output(1,stat.toString()),new StandaloneDoctor.Output(0,"broken"),new StandaloneDoctor.Output(0,"123 (x) S 1")}){
            boolean rejected=false;try{StandaloneDoctor.startTime(output);}catch(IOException e){rejected=true;}if(!rejected)throw new AssertionError("malformed generation accepted");tests++;
        }
        Path temporary=Files.createTempFile("replay-doctor-", ".zip");
        try{
            try(ZipOutputStream zip=new ZipOutputStream(Files.newOutputStream(temporary))){zip.putNextEntry(new ZipEntry("lib/arm64-v8a/libg.so"));zip.write(new byte[]{1,2,3});zip.closeEntry();}
            boolean rejected=false;try{StandaloneDoctor.libraryHash(temporary.toFile());}catch(IOException e){rejected=true;}if(!rejected)throw new AssertionError("wrong pinned library size accepted");tests++;
        }finally{Files.deleteIfExists(temporary);}
        System.out.println("PASS "+tests+" standalone doctor contract checks; no root invoked");
    }
}
