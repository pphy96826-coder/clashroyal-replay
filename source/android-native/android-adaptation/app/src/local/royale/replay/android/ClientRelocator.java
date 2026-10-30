package local.royale.replay.android;
import java.io.*;
import java.nio.*;
import java.security.*;
import java.util.*;
import java.util.zip.*;

/** Pure file analysis. Candidate locations are NEVER authorization to call native code. */
public final class ClientRelocator {
    static final int LIMIT=64*1024*1024;
    static int normalize(int w){
        if((w&0x7c000000)==0x14000000)return w&0xfc000000;
        if((w&0x9f000000)==0x10000000||(w&0x9f000000)==0x90000000)return w&0x9f00001f;
        if((w&0xff000010)==0x54000000)return w&0xff00001f;
        if((w&0x7e000000)==0x34000000)return w&0xff00001f;
        if((w&0x7e000000)==0x36000000)return w&0xfff8001f;
        if((w&0x3b000000)==0x18000000)return w&0xff00001f;
        return w;
    }
    static String hex(byte[] bytes){char[] chars=new char[bytes.length*2];String digits="0123456789abcdef";for(int i=0;i<bytes.length;i++){chars[i*2]=digits.charAt((bytes[i]&255)>>>4);chars[i*2+1]=digits.charAt(bytes[i]&15);}return new String(chars);}
    public static final class Result {
        public final Map<String,List<Long>> candidates=new LinkedHashMap<String,List<Long>>();
        public String libraryHash;public int unique,ambiguous,missing,referenceChecks,referenceRejected;public boolean candidateOnly=true;
    }
    public static Result scan(File apk,InputStream reference,String expectedReference)throws Exception {
        BufferedReader reader=new BufferedReader(new InputStreamReader(reference,"US-ASCII"));
        if(!("replay-relocation-v2 "+expectedReference).equals(reader.readLine()))throw new IOException("relocation reference mismatch");
        Map<String,List<long[]>> edges=new HashMap<String,List<long[]>>();
        Map<String,List<String>> hashes=new HashMap<String,List<String>>();Set<Integer> first=new HashSet<Integer>();Result result=new Result();String line;int count=0;
        while((line=reader.readLine())!=null){String[] parts=line.split(" ");
            if(++count>256||parts.length!=4||!parts[0].matches("[a-f0-9]{1,16}")||!parts[1].matches("[a-f0-9]{64}")||!parts[2].matches("[a-f0-9]{8}")||result.candidates.containsKey(parts[0]))throw new IOException("invalid relocation reference");
            List<long[]> links=new ArrayList<long[]>();
            if(!parts[3].equals("-"))for(String link:parts[3].split(",")){
                if(!link.matches("(?:0|4|8|12|16|20|24|28):[a-f0-9]{1,16}"))throw new IOException("invalid branch reference");
                String[] pair=link.split(":");links.add(new long[]{Long.parseLong(pair[0]),Long.parseLong(pair[1],16)});
            }
            edges.put(parts[0],links);
            result.candidates.put(parts[0],new ArrayList<Long>());List<String> keys=hashes.get(parts[1]);if(keys==null){keys=new ArrayList<String>();hashes.put(parts[1],keys);}keys.add(parts[0]);first.add((int)Long.parseLong(parts[2],16));
        }
        if(count==0)throw new IOException("empty relocation reference");
        for(List<long[]> links:edges.values())for(long[] link:links)if(!result.candidates.containsKey(Long.toHexString(link[1])))throw new IOException("unknown branch target");
        ZipFile zip=new ZipFile(apk);byte[] data;
        try{ZipEntry item=zip.getEntry("lib/arm64-v8a/libg.so");if(item==null||item.getSize()<64||item.getSize()>LIMIT)throw new IOException("relocation library limit");
            data=new byte[(int)item.getSize()];InputStream in=zip.getInputStream(item);
            try{int position=0,n;while(position<data.length&&(n=in.read(data,position,data.length-position))!=-1)position+=n;
                if(position!=data.length||in.read()!=-1)throw new IOException("incomplete relocation library");}finally{in.close();}
        }finally{zip.close();}
        MessageDigest digest=MessageDigest.getInstance("SHA-256");result.libraryHash=hex(digest.digest(data));
        ByteBuffer elf=ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN);
        if(elf.getInt(0)!=0x464c457f||data[4]!=2||data[5]!=1||elf.getShort(18)!=183)throw new IOException("ARM64 ELF required");
        long table=elf.getLong(32);int size=elf.getShort(54)&65535,number=elf.getShort(56)&65535;
        if(size!=56||number>256||table<0||table>data.length-(long)size*number)throw new IOException("invalid program table");
        byte[] normalized=new byte[32];ByteBuffer window=ByteBuffer.wrap(normalized).order(ByteOrder.LITTLE_ENDIAN);int executable=0;List<long[]> segments=new ArrayList<long[]>();
        for(int i=0;i<number;i++){int h=(int)table+i*size;if(elf.getInt(h)!=1||(elf.getInt(h+4)&1)==0)continue;executable++;
            long off=elf.getLong(h+8),va=elf.getLong(h+16),length=elf.getLong(h+32);
            if(off<0||va<0||length<32||off>data.length-length||off%4!=0||va>Long.MAX_VALUE-length)throw new IOException("invalid executable segment");
            segments.add(new long[]{off,va,length});
            for(long pos=off;pos<=off+length-32;pos+=4){int at=(int)pos;if(!first.contains(normalize(elf.getInt(at))))continue;
                for(int w=0;w<8;w++)window.putInt(w*4,normalize(elf.getInt(at+w*4)));
                List<String> keys=hashes.get(hex(digest.digest(normalized)));if(keys==null)continue;
                for(String key:keys){List<Long> matches=result.candidates.get(key);if(matches.size()<33)matches.add(va+pos-off);}
            }
        }
        if(executable==0)throw new IOException("missing executable segment");
        // Use direct call/branch relations only to reject inconsistent candidates.
        // This is not a proof of object layout or native execution compatibility.
        boolean changed;
        do{changed=false;
            for(Map.Entry<String,List<long[]>> item:edges.entrySet()){
                if(result.candidates.get(item.getKey()).size()>=33)continue;
                Iterator<Long> candidates=result.candidates.get(item.getKey()).iterator();
                while(candidates.hasNext()){
                    long candidate=candidates.next();boolean rejected=false;
                    for(long[] edge:item.getValue()){
                        List<Long> targets=result.candidates.get(Long.toHexString(edge[1]));
                        if(targets.isEmpty()||targets.size()>=33)continue;
                        long pc=candidate+edge[0];Integer instruction=null;
                        for(long[] segment:segments)if(pc>=segment[1]&&pc<=segment[1]+segment[2]-4){instruction=elf.getInt((int)(segment[0]+pc-segment[1]));break;}
                        result.referenceChecks++;
                        if(instruction==null||(instruction&0x7c000000)!=0x14000000||!targets.contains(pc+(((long)(instruction<<6))>>4))){rejected=true;break;}
                    }
                    if(rejected){candidates.remove();result.referenceRejected++;changed=true;}
                }
            }
        }while(changed);
        for(List<Long> matches:result.candidates.values()){if(matches.size()==1)result.unique++;else if(matches.isEmpty())result.missing++;else result.ambiguous++;}
        return result;
    }
    private ClientRelocator(){}
}
