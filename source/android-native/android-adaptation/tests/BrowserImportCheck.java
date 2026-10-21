package local.royale.replay.android;

import java.io.*;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.zip.GZIPOutputStream;

/** Pure JVM protocol tests. Never opens an app, socket, root or game. */
public final class BrowserImportCheck {
    private static int tests;
    private static final String URL="https://royaleapi.com/replay?tag=SYNTHETIC01&team_tags=ABCDEF";
    private static byte[] zip(byte[] bytes)throws Exception{
        ByteArrayOutputStream out=new ByteArrayOutputStream();
        try(GZIPOutputStream gzip=new GZIPOutputStream(out)){gzip.write(bytes);}return out.toByteArray();
    }
    private static String link(byte[] bytes,String source)throws Exception{
        StringBuilder hash=new StringBuilder();for(byte b:MessageDigest.getInstance("SHA-256").digest(bytes))hash.append(String.format("%02x",b&255));
        return "royalereplay://import/v1?v=1&source="+URLEncoder.encode(source,"UTF-8")+"&sha256="+hash+
            "&html_gzip="+Base64.getUrlEncoder().withoutPadding().encodeToString(zip(bytes));
    }
    private static void reject(String input)throws Exception{
        try{BrowserImport.decode(input);}catch(Exception expected){tests++;return;}
        throw new AssertionError("invalid transport accepted");
    }
    public static void main(String[] args)throws Exception{
        if(args.length==2&&args[0].equals("--decode")){
            BrowserImport.Snapshot s=BrowserImport.decode(new String(Files.readAllBytes(Paths.get(args[1])),StandardCharsets.UTF_8));
            System.out.println(s.source.tag+" "+s.source.count());return;
        }
        byte[] fixture=Files.readAllBytes(Paths.get(args[0]));String good=link(fixture,URL);
        BrowserImport.Snapshot snapshot=BrowserImport.decode(good);
        if(!Arrays.equals(snapshot.html,fixture)||snapshot.source.count()!=4||snapshot.source.firstTick!=100||snapshot.source.lastTick!=160)throw new AssertionError("source mutated");tests++;
        for(String invalid:new String[]{null,"",good.replace("royalereplay:","https:"),good.replace("//import/","//evil/"),
            good.replace("//import/","//import:80/"),good.replace("//import/","//user@import/"),good.replace("/v1?","/v2?"),
            good+"#fragment",good+"&v=1",good+"&%76=1",good+"&autoplay=true",good+"&shell=id",good+"&path=/data/x",
            good.replace("?v=1&","?v=2&"),good.replace("?v=1&","?"),good.replace("&html_gzip=","&unused="),
            good.replace("&sha256=","&sha256=0"),good+"=",good.substring(0,good.length()-5),
            good.substring(0,good.indexOf("&sha256="))+"&sha256="+String.join("",Collections.nCopies(64,"a"))+good.substring(good.indexOf("&html_gzip="))})reject(invalid);
        for(String source:new String[]{"http://royaleapi.com/replay?tag=SYNTHETIC01","https://royaleapi.com.evil.test/replay?tag=SYNTHETIC01",
            "https://evil@royaleapi.com/replay?tag=SYNTHETIC01","https://royaleapi.com:444/replay?tag=SYNTHETIC01",
            "https://royaleapi.com/player/SYNTHETIC01","https://royaleapi.com/replay?tag=SYNTHETIC01&tag=SYNTHETIC01",
            "https://royaleapi.com/replay?tag=OTHER01","https://royaleapi.com/replay?tag=SYNTHETIC01#x"})reject(link(fixture,source));
        reject(link("<html>login required</html>".getBytes(StandardCharsets.UTF_8),URL));
        reject(link(new byte[]{(byte)0xc3,0x28},URL));
        byte[] bomb=new byte[ReplaySource.MAX_BYTES+1];Arrays.fill(bomb,(byte)'A');reject(link(bomb,URL));
        byte[] random=new byte[BrowserImport.MAX_COMPRESSED+1000];new Random(42).nextBytes(random);reject(link(random,URL));
        reject(good+String.join("",Collections.nCopies(BrowserImport.MAX_URI,"A")));
        System.out.println("PASS "+tests+" browser transport checks");
    }
}
