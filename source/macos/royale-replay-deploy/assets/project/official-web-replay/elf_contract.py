"""Small bounded ELF64 reader for locally supplied AArch64 libraries."""
import hashlib
import struct


class Elf:
    def __init__(self,raw):
        self.raw=raw
        if not 64<=len(raw)<=128*1024*1024 or raw[:6]!=b'\x7fELF\x02\x01':raise ValueError('expected bounded little-endian ELF64')
        if struct.unpack_from('<H',raw,18)[0]!=183:raise ValueError('expected AArch64 ELF')
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
