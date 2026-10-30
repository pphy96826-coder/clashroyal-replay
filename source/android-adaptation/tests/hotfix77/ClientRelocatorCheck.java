package local.royale.replay.android;
import java.io.*;
public class ClientRelocatorCheck {
 public static void main(String[] args)throws Exception {
  try(InputStream reference=new FileInputStream(args[1])){
   ClientRelocator.Result r=ClientRelocator.scan(new File(args[0]),reference,args[2]);
   if(!r.candidateOnly)throw new AssertionError("candidate scan cannot approve native execution");
   System.out.println("unique="+r.unique+" ambiguous="+r.ambiguous+" missing="+r.missing+" total="+r.candidates.size()+" refs="+r.referenceChecks+" rejected="+r.referenceRejected);
  }
 }
}
