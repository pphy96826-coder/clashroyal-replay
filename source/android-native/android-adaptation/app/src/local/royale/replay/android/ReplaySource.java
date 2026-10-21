package local.royale.replay.android;

import java.util.*;
import java.util.regex.*;

/** Bounded source precheck only. Full deck/native validation stays in backend. */
public final class ReplaySource {
    public static final int MAX_BYTES=25*1024*1024;
    public static final class Info {
        public String tag;
        public int plays,abilities,firstTick=Integer.MAX_VALUE,lastTick,orientation=-1;
        public final List<Map<String,String>> events=new ArrayList<Map<String,String>>();
        public int count(){return plays+abilities;}
    }
    private static String entity(String value) {
        return value.replace("&quot;","\"").replace("&#39;","'").replace("&lt;","<").replace("&gt;",">").replace("&amp;","&");
    }
    private static Map<String,String> attrs(String text) {
        Map<String,String> values=new HashMap<String,String>();
        Pattern p=Pattern.compile("([A-Za-z_:][A-Za-z0-9_:.-]*)\\s*=\\s*(?:\"([^\"]*)\"|'([^']*)'|([^\\s>]+))");
        Matcher m=p.matcher(text);
        while(m.find()) {
            String key=m.group(1).toLowerCase(Locale.ROOT);
            String value=m.group(2)!=null?m.group(2):m.group(3)!=null?m.group(3):m.group(4);
            if(values.put(key,entity(value))!=null)throw new IllegalArgumentException("重复属性，拒绝猜测来源");
        }
        return values;
    }
    public static Info parse(String html) {
        if(html.length()>MAX_BYTES)throw new IllegalArgumentException("HTML 超过25MB");
        Info info=new Info();String lower=html.toLowerCase(Locale.ROOT);int pos=0;
        while(pos<html.length()) {
            int begin=html.indexOf('<',pos);if(begin<0)break;
            if(html.startsWith("<!--",begin)) {int end=html.indexOf("-->",begin+4);if(end<0)break;pos=end+3;continue;}
            int end=begin+1;char quote=0;
            for(;end<html.length();end++){char c=html.charAt(end);if(quote!=0){if(c==quote)quote=0;}else if(c=='\''||c=='\"')quote=c;else if(c=='>')break;}
            if(end>=html.length())break;
            String token=html.substring(begin+1,end);pos=end+1;
            String name=token.split("[\\s/]",2)[0].toLowerCase(Locale.ROOT);
            if(name.equals("script")||name.equals("style")){int close=lower.indexOf("</"+name,pos);if(close<0)break;pos=close;continue;}
            if(token.startsWith("/")||token.startsWith("!")||token.startsWith("?"))continue;
            Map<String,String> a=attrs(token);String cls=a.get("class");
            if(cls!=null&&Arrays.asList(cls.split("\\s+")).contains("battle_replay")&&a.containsKey("data-tag")){
                String tag=a.get("data-tag").replaceFirst("^#","");
                if(!tag.matches("[A-Z0-9]{6,32}")||(info.tag!=null&&!info.tag.equals(tag)))throw new IllegalArgumentException("回放编号不唯一或无效");
                info.tag=tag;
            }
            if(!a.containsKey("data-t")||!a.containsKey("data-s"))continue;
            boolean ability=a.containsKey("data-ability")&&!a.get("data-ability").isEmpty()&&!a.get("data-ability").equals("0");
            boolean play=a.containsKey("data-x")&&a.containsKey("data-y")&&a.containsKey("data-c")&&!a.get("data-x").equals("None")&&!a.get("data-y").equals("None");
            if(!ability&&!play)continue;
            String side=a.get("data-s");if(!side.equals("blue")&&!side.equals("red")&&!side.equals("t")&&!side.equals("o"))throw new IllegalArgumentException("未知所属方");
            int tick=Integer.parseInt(a.get("data-t"));if(tick<0||tick>1000000)throw new IllegalArgumentException("来源时刻越界");
            if(a.containsKey("data-i")&&!a.get("data-i").isEmpty()){
                int orientation=Integer.parseInt(a.get("data-i"));if(orientation!=0&&orientation!=1)throw new IllegalArgumentException("来源方向无效");
                if(info.orientation!=-1&&info.orientation!=orientation)throw new IllegalArgumentException("来源方向混合");info.orientation=orientation;
            }
            if(ability)info.abilities++;
            else {int x=Integer.parseInt(a.get("data-x")),y=Integer.parseInt(a.get("data-y"));if(x<0||x>=18000||y<0||y>=32000)throw new IllegalArgumentException("出牌坐标越界");info.plays++;}
            info.firstTick=Math.min(info.firstTick,tick);info.lastTick=Math.max(info.lastTick,tick);info.events.add(new HashMap<String,String>(a));
            if(info.count()>10000)throw new IllegalArgumentException("事件数量超过安全上限");
        }
        if(info.tag==null||info.plays==0||info.orientation<0)throw new IllegalArgumentException("没有完整的回放标记、出牌坐标或方向");
        return info;
    }
    private ReplaySource(){}
}
