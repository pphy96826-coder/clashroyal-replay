package local.royale.replay.android;

import java.net.URI;
import java.net.URLDecoder;
import java.util.Locale;

/** Pure, testable source rules. Routing is app-local, explicit DIRECT. */
final class BrowserPolicy {
    static boolean allowed(String url){try{
        URI uri=new URI(url);String host=uri.getHost();
        if(!"https".equalsIgnoreCase(uri.getScheme())||uri.getUserInfo()!=null||(uri.getPort()!=-1&&uri.getPort()!=443)||host==null)return false;
        host=host.toLowerCase(Locale.ROOT);
        return host.equals("royaleapi.com")||host.endsWith(".royaleapi.com")||host.equals("challenges.cloudflare.com")||host.equals("cdnjs.cloudflare.com")||host.equals("cdn.jsdelivr.net")||host.equals("fonts.googleapis.com")||host.equals("fonts.gstatic.com");
    }catch(Exception e){return false;}}
    static String replayTag(String url){try{
        URI uri=new URI(url);String host=uri.getHost();
        if(!allowed(url)||!("royaleapi.com".equalsIgnoreCase(host)||"www.royaleapi.com".equalsIgnoreCase(host))||!"/replay".equals(uri.getPath())||uri.getRawQuery()==null)return "";
        String tag="";
        for(String part:uri.getRawQuery().split("&")){
            String[] kv=part.split("=",2);
            if(URLDecoder.decode(kv[0],"UTF-8").equals("tag")){
                if(!tag.isEmpty()||kv.length!=2)return "";
                tag=URLDecoder.decode(kv[1],"UTF-8");
            }
        }
        return tag.matches("[A-Z0-9]{6,32}")?tag:"";
    }catch(Exception e){return "";}}
    private BrowserPolicy(){}
}
