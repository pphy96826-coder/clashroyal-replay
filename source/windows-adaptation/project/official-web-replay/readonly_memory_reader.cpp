// Local read-only transport. No hooks, writes, networking or native game calls.
// Built with a static C++ runtime; no client or device libc++ dependency.
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <cstring>
#include <fcntl.h>
#include <unistd.h>

static bool input(void* data,size_t size){return std::fread(data,1,size,stdin)==size;}
static bool generation(int pid,const char* expected){
    char path[64],line[4096];std::snprintf(path,sizeof(path),"/proc/%d/stat",pid);
    FILE* stream=std::fopen(path,"r");if(!stream)return false;
    bool okay=std::fgets(line,sizeof(line),stream)!=nullptr;std::fclose(stream);
    if(!okay)return false;char* end=std::strrchr(line,')');if(!end)return false;
    char* saved=nullptr;char* token=strtok_r(end+1," \n",&saved);
    for(int index=0;index<19&&token;++index)token=strtok_r(nullptr," \n",&saved);
    return token&&std::strcmp(token,expected)==0;
}
int main(int argc,char** argv){
    if(argc!=3)return 2;char* end=nullptr;long pid=std::strtol(argv[1],&end,10);
    if(!end||*end||pid<=0||pid>=(1<<22)||!generation(pid,argv[2]))return 3;
    uint32_t count=0;if(!input(&count,4)||count>4096)return 4;
    struct Request{uint64_t address;uint32_t size;};Request requests[4096];size_t total=0;
    for(uint32_t i=0;i<count;++i){auto& r=requests[i];
        if(!input(&r.address,8)||!input(&r.size,4)||!r.address||r.address>INT64_MAX||
           !r.size||r.size>4096||total+r.size>65536)return 5;
        total+=r.size;
    }
    char path[64];std::snprintf(path,sizeof(path),"/proc/%ld/mem",pid);
    int file=open(path,O_RDONLY|O_CLOEXEC);if(file<0)return 6;
    unsigned char output[65536];size_t offset=0;
    for(uint32_t i=0;i<count;++i){auto& r=requests[i];
        if(pread(file,output+offset,r.size,r.address)!=r.size){close(file);return 7;}
        offset+=r.size;
    }
    close(file);if(!generation(pid,argv[2]))return 8;
    return std::fwrite(output,1,total,stdout)==total?0:9;
}
