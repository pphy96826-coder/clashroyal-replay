"""Small bounded ELF64 reader for locally supplied AArch64 libraries."""
import hashlib
import struct


class Elf:
    def __init__(self,raw,machine=183):
        self.raw=raw
        if not 64<=len(raw)<=128*1024*1024 or raw[:6]!=b'\x7fELF\x02\x01':raise ValueError('expected bounded little-endian ELF64')
        if machine not in (62,183) or struct.unpack_from('<H',raw,18)[0]!=machine:raise ValueError('unexpected ELF machine')
        self.phoff=struct.unpack_from('<Q',raw,32)[0]
        phsize,phcount=struct.unpack_from('<HH',raw,54)
        if phsize!=56 or phcount>128:raise ValueError('unsupported ELF program table')
        self.programs=[struct.unpack('<II6Q',self.slice(self.phoff+i*56,56)) for i in range(phcount)]

    def slice(self,offset,size):
        if not 0<=offset<=len(self.raw) or not 0<=size<=len(self.raw)-offset:raise ValueError('ELF range outside file')
        return self.raw[offset:offset+size]

    def at(self,va,size):
        matches=[p for p in self.programs if p[0]==1 and p[3]<=va and va+size<=p[3]+p[5]]
        if len(matches)!=1:raise ValueError('ELF address is not uniquely file-backed')
        p=matches[0];return self.slice(p[2]+va-p[3],size)

    def exports(self,names):
        shoff=struct.unpack_from('<Q',self.raw,40)[0]
        entsize,count=struct.unpack_from('<HH',self.raw,58)
        if entsize!=64 or count>4096:raise ValueError('unsupported ELF section table')
        sections=[struct.unpack('<II4QII2Q',self.slice(shoff+i*64,64)) for i in range(count)]
        result={}
        for section in sections:
            if section[1]!=11:continue
            if section[9]!=24 or section[6]>=len(sections):raise ValueError('invalid ELF dynamic symbols')
            strings=sections[section[6]];text=self.slice(strings[4],strings[5])
            if section[5]//24>2000000:raise ValueError('excessive ELF symbol count')
            for i in range(section[5]//24):
                name,info,other,index,va,size=struct.unpack('<IBBHQQ',self.slice(section[4]+i*24,24))
                if not index or name>=len(text):continue
                end=text.find(b'\0',name)
                if end<0:raise ValueError('unterminated symbol')
                value=text[name:end].decode('ascii',errors='replace')
                if value not in names:continue
                if value in result or not 0<size<=4096:raise ValueError('ambiguous/unbounded export')
                result[value]=dict(va=hex(va),size=size,sha256=hashlib.sha256(self.at(va,size)).hexdigest())
        if set(result)!=set(names):raise ValueError('required native exports missing')
        return result

    def relative_pointer(self,va):
        shoff=struct.unpack_from('<Q',self.raw,40)[0]
        entsize,count=struct.unpack_from('<HH',self.raw,58)
        if entsize!=64 or count>4096:raise ValueError('unsupported ELF section table')
        found=[]
        for i in range(count):
            section=struct.unpack('<II4QII2Q',self.slice(shoff+i*64,64))
            if section[1]!=4:continue
            if section[9]!=24 or section[5]//24>2000000:raise ValueError('invalid ELF relocation table')
            for j in range(section[5]//24):
                offset,info,addend=struct.unpack('<QQq',self.slice(section[4]+24*j,24))
                if offset==va:
                    if info!=8 or addend<=0:raise ValueError('expected relative x86_64 relocation')
                    found.append(addend)
        if len(found)!=1:raise ValueError('relative pointer absent or ambiguous')
        return found[0]

    def object_symbol(self,name,kind=1):
        """One bounded local object in our own unstripped diagnostic image."""
        shoff=struct.unpack_from('<Q',self.raw,40)[0];entsize,count=struct.unpack_from('<HH',self.raw,58)
        if entsize!=64 or count>4096:raise ValueError('unsupported ELF section table')
        sections=[struct.unpack('<II4QII2Q',self.slice(shoff+i*64,64)) for i in range(count)]
        found=[]
        for section in sections:
            if section[1]!=2:continue
            if section[9]!=24 or section[6]>=len(sections) or section[5]//24>2000000:raise ValueError('invalid ELF symbols')
            strings=sections[section[6]];text=self.slice(strings[4],strings[5])
            for i in range(section[5]//24):
                start,info,other,index,va,size=struct.unpack('<IBBHQQ',self.slice(section[4]+24*i,24))
                if start>=len(text):raise ValueError('invalid ELF symbol string')
                end=text.find(b'\0',start)
                if end<0:raise ValueError('unterminated ELF symbol string')
                if text[start:end]!=name.encode('ascii'):continue
                if not index or index>=len(sections) or info&15!=kind or not 0<size<=4096:raise ValueError('invalid object symbol')
                found.append((va,size))
        if len(found)!=1:raise ValueError('object symbol absent or ambiguous')
        return found[0]
