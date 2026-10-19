// Translation-specific, single-publication empty-task diagnostic.
// The upstream task and publisher implementation is compiled unchanged.
#include "../offline-queue-runtime/empty_publisher.h"
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <pthread.h>
#include <unistd.h>
#include <climits>
#include MUMU_WORKER_BINDINGS
#define EXPORT extern "C" __attribute__((visibility("default")))

static CrNoopRequest* request{};
static std::atomic<bool> attempted{false};
static int publisher_result=EMPTY_IDLE;
static uint64_t fields[16]{};
static uint64_t validation_stage{},observed_import{},expected_import{};
template<class T> static T read(uintptr_t p) { T v{}; std::memcpy(&v,(void*)p,sizeof(v)); return v; }
static bool mapped(uintptr_t p,size_t size,const char* required,bool guest_text=false) {
    if (!p || p+size<p) return false;
    FILE* f=std::fopen("/proc/self/maps","r"); if (!f) return false;
    char line[2048]; bool found=false;
    while (std::fgets(line,sizeof(line),f)) {
        unsigned long long low{},high{},offset{}; char mode[5]{},path[1536]{};
        int n=std::sscanf(line,"%llx-%llx %4s %llx %*s %*s %1535s",&low,&high,mode,&offset,path);
        if (n<4 || low>p || high<p+size) continue;
        found=true;
        for (const char* r=required;*r;++r) if (!std::strchr(mode,*r)) found=false;
        if (guest_text && (n!=5 || low!=expected_base || high-low!=0x1b3d000 || offset!=0x284d000 ||
            std::strcmp(mode,"r--p") || std::strcmp(path,expected_apk))) found=false;
        break;
    }
    std::fclose(f); return found;
}
static bool validated(uintptr_t b,int pid,uint64_t tid,uintptr_t handle,uintptr_t services) {
    validation_stage=1;
    if (b!=expected_base || pid!=expected_pid || pid!=getpid() || tid!=expected_tid ||
        tid==cr_noop_current_tid() || handle!=expected_handle || services!=expected_services ||
        !mapped(b,64,"r",true) || read<uint32_t>(b)!=0x464c457f ||
        !mapped(b+0x1d88818,0x110,"rw") || !mapped(handle,0x18,"r") ||
        !mapped(b+0x1d34ae0,8,"r")) return false;
    validation_stage=2; uintptr_t root=read<uintptr_t>(b+0x1d34ae0);
    if (root!=expected_root || !mapped(root+0x20,8,"r") || read<uintptr_t>(root+0x20)!=services ||
        read<uintptr_t>(b+0x1d88818)!=b+0x1c4a2e8 || read<uintptr_t>(b+0x1d88820)!=handle ||
        read<int>(handle+0x10)!=static_cast<int>(tid)) return false;
    struct Pin {uintptr_t va;uint32_t word;};
    const Pin pins[]={{0x1629ab4,0xa94fd674},{0x1629abc,0xa90ffe7f},{0x1629ac0,0xf900867f},
        {0x1629ae8,0xf9400908},{0x1629b24,0xf9400508},{0x1629b44,0x94142b7d},
        {0x1b34938,0xd503245f},{0x1b3493c,0x14001d39}};
    validation_stage=3;
    for (const auto& p:pins) if (!mapped(b+p.va,4,"r",true) || read<uint32_t>(b+p.va)!=p.word) return false;
    struct Import {uintptr_t va;uintptr_t target;};
    // Live import slots, each bound against a named verified proxy export.
    const Import imports[]={{0x1c72ba8,expected_malloc},{0x1c72bb0,expected_free},
        {0x1c72de0,expected_pthread_mutex_lock},{0x1c72df8,expected_pthread_mutex_unlock},
        {0x1c72e68,expected_pthread_cond_signal},{0x1c731b8,expected_pthread_mutex_trylock}};
    for (unsigned n=0;n<sizeof(imports)/sizeof(imports[0]);++n) {
        const auto& i=imports[n]; validation_stage=10+n;
        expected_import=i.target;
        if (!mapped(b+i.va,8,"r")) return false;
        observed_import=read<uintptr_t>(b+i.va);
        if (observed_import!=expected_import) return false;
    }
    validation_stage=100;
    return true;
}
// Same empty-queue ownership protocol as upstream. The queue buffer and POSIX
// operations use the game's individually verified imports, not another proxy
// namespace. Request/task allocations remain owned entirely by this module.
static int publish_game_empty(void* opaque,CrNoopTask* task) noexcept {
    auto* b=static_cast<EmptyBinding*>(opaque);
    auto allocate=reinterpret_cast<void*(*)(size_t)>(expected_malloc);
    auto deallocate=reinterpret_cast<void(*)(void*)>(expected_free);
    auto trylock=reinterpret_cast<int(*)(pthread_mutex_t*)>(expected_pthread_mutex_trylock);
    auto unlock=reinterpret_cast<int(*)(pthread_mutex_t*)>(expected_pthread_mutex_unlock);
    auto signal=reinterpret_cast<int(*)(pthread_cond_t*)>(expected_pthread_cond_signal);
    auto* storage=static_cast<CrNoopTask**>(allocate(sizeof(task)));
    if (!storage) {b->result=EMPTY_ALLOCATION;return 0;}
    auto* primary=reinterpret_cast<pthread_mutex_t*>(b->loop+0x14);
    auto* wake=reinterpret_cast<pthread_mutex_t*>(b->loop+0x3c);
    if (trylock(primary)) {deallocate(storage);b->result=EMPTY_PRIMARY_BUSY;return 0;}
    uintptr_t v[3]{};std::memcpy(v,b->loop+0xf8,sizeof(v));
    if (v[0]||v[1]||v[2]) {unlock(primary);deallocate(storage);b->result=EMPTY_NOT_EMPTY;return 0;}
    if (trylock(wake)) {unlock(primary);deallocate(storage);b->result=EMPTY_WAKE_BUSY;return 0;}
    uint32_t count=read<uint32_t>(reinterpret_cast<uintptr_t>(b->loop)+0x94);
    if (count>=INT_MAX) {unlock(wake);unlock(primary);deallocate(storage);b->result=EMPTY_WAKE_OVERFLOW;return 0;}
    storage[0]=task;auto begin=reinterpret_cast<uintptr_t>(storage);
    const uintptr_t after[3]={begin,begin+8,begin+8};std::memcpy(b->loop+0xf8,after,sizeof(after));
    ++count;std::memcpy(b->loop+0x94,&count,sizeof(count));
    int a=unlock(wake),c=signal(reinterpret_cast<pthread_cond_t*>(b->loop+0x64)),d=unlock(primary);
    b->result=a||c||d?EMPTY_POSIX_ERROR:EMPTY_POSTED;return 1;
}
EXPORT int rr_mumu_worker_start(uint64_t base,int pid,uint64_t tid,uint64_t handle,uint64_t services) {
    if (attempted.exchange(true)) return -10; // a failure never permits republication
    if (!validated(base,pid,tid,handle,services)) return -11;
    auto* task=cr_noop_prepare(tid,&request); if (!task) return -12;
    EmptyBinding binding{reinterpret_cast<unsigned char*>(base+0x1d88818)};
    int result=cr_noop_submit(task,publish_game_empty,&binding); publisher_result=binding.result; return result;
}
EXPORT uint64_t rr_mumu_worker_snapshot() {
    CrNoopSnapshot s{};
    fields[0]=publisher_result; fields[1]=attempted.load(); fields[2]=request!=nullptr;
    fields[12]=validation_stage; fields[13]=observed_import; fields[14]=expected_import;
    if (request && cr_noop_snapshot(request,&s)) {
        fields[3]=s.phase; fields[4]=s.submitted; fields[5]=s.entered; fields[6]=s.returned;
        fields[7]=s.destroyed; fields[8]=s.expected_tid; fields[9]=s.execution_tid; fields[10]=s.destruction_tid;
    }
    return reinterpret_cast<uintptr_t>(fields);
}
EXPORT int rr_mumu_worker_release() {
    if (!request) return 0;
    CrNoopSnapshot s{}; cr_noop_snapshot(request,&s);
    if (!s.destroyed) return -1;
    cr_noop_release_request(request); request=nullptr; return 1;
    // The module stays loaded until process exit. Host stack PCs cannot prove
    // absence of a translated ARM return address; never dlclose it here.
}
