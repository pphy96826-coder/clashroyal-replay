#include <stdint.h>
static uint64_t data[5];
#ifdef RR_MUMU_DYNAMIC_TEST
#include <dlfcn.h>
static void* last_handle;
#endif
static uint64_t wide() { return 0xfedcba9876543210ULL; }
static int negative() { return -7; }
static int start(uint64_t a,int b,uint64_t c,uint64_t d,uint64_t e) {
    data[0]=a;data[1]=static_cast<uint64_t>(b);data[2]=c;data[3]=d;data[4]=e;return 1;
}
static int pointer(void* p) { return p==data?1:0; }
static void* open(const char* path,int flags) {
    const char expected[]="/data/local/tmp/royale_replay_probe/fixture.so";
    if(flags!=2 || !path) return nullptr;
    for(unsigned i=0;i<sizeof(expected);++i) if(path[i]!=expected[i]) return nullptr;
    return data;
}
#ifdef RR_MUMU_DYNAMIC_TEST
static void* real_open(const char* path,int flags) {
    last_handle=dlopen(path,flags);
    return last_handle;
}
#endif
extern "C" __attribute__((visibility("default")))
uint64_t Java_RoyaleReplayBridge_testAddress(void*,void*,uint64_t kind) {
    switch(kind) {
        case 1:return reinterpret_cast<uint64_t>(wide);
        case 2:return reinterpret_cast<uint64_t>(negative);
        case 3:return reinterpret_cast<uint64_t>(start);
        case 4:return reinterpret_cast<uint64_t>(pointer);
        case 5:return reinterpret_cast<uint64_t>(open);
        case 6:return reinterpret_cast<uint64_t>(data);
#ifdef RR_MUMU_DYNAMIC_TEST
        case 7:return reinterpret_cast<uint64_t>(real_open);
        case 8:return reinterpret_cast<uint64_t>(&dlclose);
        case 9:return last_handle?reinterpret_cast<uint64_t>(dlsym(last_handle,"rr_fixture_value")):0;
#endif
        default:return 0;
    }
}
