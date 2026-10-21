// Private companion-file transport for trimmed test images without run-as.
// Starts ONLY under already-authorized adb root, drops to our app UID first.
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/prctl.h>
#include <grp.h>
#include <fcntl.h>
#include <dirent.h>
#include <unistd.h>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

static int fail(const char* message){std::fprintf(stderr,"%s (%d)\n",message,errno);return 2;}
static bool idchar(char c){return (c>='a'&&c<='f')||(c>='0'&&c<='9')||c=='-';}
static bool safe(const std::string& name){
    if(name=="pairing.json"||name=="source.json")return true;
    std::string rest=name;
    if(rest.rfind("jobs/",0)==0)rest=rest.substr(5);
    else if(rest.rfind("status-",0)==0)rest=rest.substr(7);
    else return false;
    if(rest.size()!=41||rest.substr(36)!=".json"){
        if(rest.size()!=41||rest.substr(36)!=".html")return false;
    }
    for(size_t i=0;i<36;++i)if(!idchar(rest[i]))return false;
    return true;
}
int main(int argc,char** argv){
    if(argc<3||argc>4)return fail("usage: UID read|write|list [private-name]");
    char* end=nullptr;long uid=std::strtol(argv[1],&end,10);
    if(!end||*end||uid<10000||uid>199999)return fail("invalid own-app uid");
    const char* base="/data/user/0/local.royale.replay.android/files";
    struct stat st{};if(lstat(base,&st)||!S_ISDIR(st.st_mode)||st.st_uid!=static_cast<uid_t>(uid))return fail("own app directory changed");
    if(geteuid()!=0)return fail("existing authorized adb root required; no escalation attempted");
    if(setgroups(0,nullptr)||setresgid(uid,uid,uid)||setresuid(uid,uid,uid)||geteuid()!=uid)return fail("cannot drop to own app uid");
    if(prctl(PR_SET_NO_NEW_PRIVS,1,0,0,0))return fail("cannot bind unprivileged operation");
    int root=open(base,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);if(root<0)return fail("own-app access denied");
    std::string op=argv[2];
    if(op=="list"){
        int fd=openat(root,"jobs",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
        if(fd<0){close(root);return errno==ENOENT?0:fail("cannot list own jobs");}
        DIR* dir=fdopendir(fd);if(!dir)return fail("cannot enumerate jobs");
        size_t count=0;while(dirent* entry=readdir(dir)){std::string name=entry->d_name;if(safe("jobs/"+name)&&name.substr(36)==".json"){if(++count>1000)return fail("too many jobs");std::puts(name.c_str());}}
        closedir(dir);close(root);return 0;
    }
    if(argc!=4||!safe(argv[3]))return fail("unsupported private path");
    std::string name=argv[3];int folder=root;
    if(name.rfind("jobs/",0)==0){folder=openat(root,"jobs",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);if(folder<0)return fail("missing jobs");name=name.substr(5);}
    if(op=="read"){
        int fd=openat(folder,name.c_str(),O_RDONLY|O_NOFOLLOW|O_CLOEXEC);
        if(fd<0)return fail("private file not found");
        if(fstat(fd,&st)||!S_ISREG(st.st_mode)||st.st_size<0||st.st_size>25*1024*1024)return fail("invalid private file");
        char buf[16384];ssize_t n;
        while((n=read(fd,buf,sizeof(buf)))>0){ssize_t p=0;while(p<n){ssize_t w=write(STDOUT_FILENO,buf+p,n-p);if(w<=0)return fail("short output");p+=w;}}
        if(n<0)return fail("private read failed");close(fd);
    }else if(op=="write"){
        if(folder!=root||(name!="pairing.json"&&name.rfind("status-",0)!=0))return fail("only pairing/status writes allowed");
        std::string temp=name+".tmp."+std::to_string(getpid());int fd=openat(root,temp.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
        if(fd<0)return fail("private temp exists");size_t total=0;char buf[8192];ssize_t n;
        while((n=read(STDIN_FILENO,buf,sizeof(buf)))>0){total+=n;if(total>32768)return fail("status too large");ssize_t p=0;while(p<n){ssize_t w=write(fd,buf+p,n-p);if(w<=0)return fail("short private write");p+=w;}}
        if(n<0||fsync(fd))return fail("private write failed");close(fd);
        if(renameat(root,temp.c_str(),root,name.c_str()))return fail("private atomic publish failed");
    }else return fail("unsupported operation");
    if(folder!=root)close(folder);close(root);return 0;
}
