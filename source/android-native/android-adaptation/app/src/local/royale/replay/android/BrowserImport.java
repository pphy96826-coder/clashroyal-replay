package local.royale.replay.android;

import java.io.*;
import java.net.URI;
import java.net.URLDecoder;
import java.nio.ByteBuffer;
import java.nio.charset.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.zip.GZIPInputStream;

/** Untrusted, bounded browser transport. No Android, network, files or native calls. */
final class BrowserImport {
    static final int MAX_COMPRESSED=160*1024, MAX_URI=240*1024;
    static final class Snapshot {
        final String url,sha256;
        final byte[] html;
        final ReplaySource.Info source;
        Snapshot(String url,String sha256,byte[] html,ReplaySource.Info source){
            this.url=url;this.sha256=sha256;this.html=html;this.source=source;
        }
    }
    static Snapshot decode(String link)throws Exception {
        if(link==null||link.length()>MAX_URI)throw new IOException("浏览器数据超过传输上限，请保存 HTML 后在控制台选择文件");
        URI uri=new URI(link);
        if(!"royalereplay".equals(uri.getScheme())||!"import".equals(uri.getRawAuthority())||
           !"/v1".equals(uri.getRawPath())||uri.getRawFragment()!=null||uri.getRawQuery()==null)
            throw new IOException("不是受支持的本机回放导入链接");
        Map<String,String> fields=new HashMap<String,String>();
        for(String part:uri.getRawQuery().split("&",-1)){
            String[] kv=part.split("=",2);
            if(kv.length!=2)throw new IOException("浏览器数据字段不完整");
            String key=URLDecoder.decode(kv[0],"UTF-8"),value=URLDecoder.decode(kv[1],"UTF-8");
            if(!Arrays.asList("v","source","sha256","html_gzip").contains(key)||fields.put(key,value)!=null)
                throw new IOException("未知或重复的浏览器数据字段");
        }
        if(fields.size()!=4||!"1".equals(fields.get("v")))throw new IOException("请更新浏览器桥接脚本");
        String url=fields.get("source"),hash=fields.get("sha256"),encoded=fields.get("html_gzip");
        String tag=BrowserPolicy.replayTag(url);
        if(url.length()>8192||tag.isEmpty()||new URI(url).getRawFragment()!=null)
            throw new IOException("仅接受 HTTPS RoyaleAPI Replay 详情页");
        if(!hash.matches("[a-f0-9]{64}")||encoded.isEmpty()||encoded.length()>(MAX_COMPRESSED*4+2)/3||!encoded.matches("[A-Za-z0-9_-]+"))
            throw new IOException("浏览器数据校验字段无效或过大");
        byte[] compressed=Base64.getUrlDecoder().decode(encoded);
        if(compressed.length>MAX_COMPRESSED||!Base64.getUrlEncoder().withoutPadding().encodeToString(compressed).equals(encoded))
            throw new IOException("压缩数据超限或编码不规范");
        ByteArrayOutputStream out=new ByteArrayOutputStream();
        try(InputStream in=new GZIPInputStream(new ByteArrayInputStream(compressed))){
            byte[] block=new byte[16384];int count;
            while((count=in.read(block))!=-1){
                if(out.size()+count>ReplaySource.MAX_BYTES)throw new IOException("解压后的 HTML 超过25MB");
                out.write(block,0,count);
            }
        }
        byte[] bytes=out.toByteArray();
        byte[] digest=MessageDigest.getInstance("SHA-256").digest(bytes),expected=new byte[32];
        for(int i=0;i<32;i++)expected[i]=(byte)Integer.parseInt(hash.substring(i*2,i*2+2),16);
        if(!MessageDigest.isEqual(digest,expected))throw new IOException("HTML 内容校验失败，未导入或播放");
        String html=StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
        ReplaySource.Info parsed=ReplaySource.parse(html);
        if(!tag.equals(parsed.tag))throw new IOException("网页网址与 HTML 中的回放编号不一致");
        return new Snapshot(url,hash,bytes,parsed);
    }
    private BrowserImport(){}
}
