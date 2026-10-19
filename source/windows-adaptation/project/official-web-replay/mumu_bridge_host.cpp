// NativeBridge ABI reference: AOSP art/libnativebridge/include/nativebridge/native_bridge.h.
// Only the v3-v6 prefix is used. This module never initializes a game's bridge.
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <jni.h>

struct RuntimeCallbacks {
    const char* (*shorty)(void*,void*);
    uint32_t (*count)(void*,void*);
    uint32_t (*methods)(void*,void*,void*,uint32_t);
};
struct Bridge {
    uint32_t version;
    bool (*initialize)(const RuntimeCallbacks*,const char*,const char*);
    void* (*load)(const char*,int);
    void* (*trampoline)(void*,const char*,const char*,uint32_t);
    bool (*supported)(const char*);
    void* (*appEnv)(const char*);
    bool (*compatible)(uint32_t);
    void* (*signalHandler)(int);
    int (*unload)(void*);
    const char* (*error)();
    bool (*pathSupported)(const char*);
    bool (*anonymousNamespace)(const char*,const char*);
    void* (*createNamespace)(const char*,const char*,const char*,uint64_t,const char*,void*);
    bool (*linkNamespaces)(void*,void*,const char*);
    void* (*loadExt)(const char*,int,void*);
    void* (*vendorNamespace)();
    void* (*exportedNamespace)(const char*);
};
using Dispatch=uint64_t(*)(void*,void*,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t);
static Dispatch dispatch;
#if defined(RR_MUMU_STANDALONE_TEST) || defined(RR_MUMU_ART_TEST)
static void* fixture_guest;
static Bridge* fixture_bridge;
#endif
static char bound_path[1024];
static char last_error[512];
using GetVMs=jint(*)(JavaVM**,jsize,jsize*);
static GetVMs borrowed_vms;
static JNIEnv* environment() {
#ifdef RR_MUMU_STANDALONE_TEST
    return nullptr;
#else
    auto get_vms=borrowed_vms?borrowed_vms:reinterpret_cast<GetVMs>(dlsym(RTLD_DEFAULT,"JNI_GetCreatedJavaVMs"));
    if(!get_vms) {
        void* art=dlopen("/apex/com.android.art/lib64/libart.so",RTLD_NOW|RTLD_NOLOAD);
        if(art) get_vms=reinterpret_cast<GetVMs>(dlsym(art,"JNI_GetCreatedJavaVMs"));
    }
    JavaVM* vm=nullptr;jsize count=0;
    if(!get_vms || get_vms(&vm,1,&count)!=JNI_OK || count!=1 || !vm) return nullptr;
    JNIEnv* env=nullptr;
    return vm->GetEnv(reinterpret_cast<void**>(&env),JNI_VERSION_1_6)==JNI_OK?env:nullptr;
#endif
}
static int error(const char* text) {
    snprintf(last_error,sizeof(last_error),"%s",text?text:"NativeBridge failed without diagnostic");
    return 0;
}
extern "C" __attribute__((visibility("default")))
const char* rr_mumu_error() { return last_error; }

static int bind_impl(const char* path,bool require_initialized,Bridge* borrowed=nullptr,bool(*initialized_api)()=nullptr) {
    bool owned=path && !strncmp(path,"/data/local/tmp/royale_",23);
#ifdef RR_MUMU_ART_TEST
    owned=owned || (path && !strncmp(path,"/data/user/0/org.codex.mumu.replayprobe/files/",43));
#endif
    if(!owned || strlen(path)>=sizeof(bound_path))
        return error("unexpected owned guest library path");
    if(dispatch) return strcmp(path,bound_path)==0 ? 1 : error("another guest relay already owns this helper");
    auto initialized=initialized_api;
    if(!initialized) {
        void* api=dlopen("/apex/com.android.art/lib64/libnativebridge.so",RTLD_NOW|RTLD_LOCAL);
        if(!api) return error(dlerror());
        initialized=reinterpret_cast<bool(*)()>(dlsym(api,"NativeBridgeInitialized"));
    }
    if(require_initialized && (!initialized || !initialized()))
        return error("ART NativeBridge is not already initialized in this process");
    auto* bridge=borrowed;
    if(!bridge) {
        void* lib=dlopen("/system/lib64/libnb.so",RTLD_NOW|RTLD_LOCAL);
        if(!lib) return error(dlerror());
        bridge=static_cast<Bridge*>(dlsym(lib,"NativeBridgeItf"));
    }
    if(!bridge || bridge->version<3 || bridge->version>6) return error("unsupported NativeBridge interface");
    if(!bridge->createNamespace || !bridge->loadExt || !bridge->trampoline)
        return error("required NativeBridge callbacks absent");
    // A separate non-isolated namespace, local to this component. Do not reset
    // the app's anonymous namespace or change any game's loader state.
    void* ns=bridge->createNamespace("royale-replay-relay","/data/local/tmp",
        "/system/lib64/arm64/nb:/system/lib64/arm64",0,nullptr,nullptr);
    if(!ns) return error(bridge->error());
    void* guest=bridge->loadExt(path,RTLD_NOW,ns);
    if(!guest) return error(bridge->error());
    auto fn=reinterpret_cast<Dispatch>(bridge->trampoline(guest,
        "Java_RoyaleReplayBridge_dispatch","JJJJJJJJ",8));
    if(!fn) return error(bridge->error());
    JNIEnv* env=environment();
    if(require_initialized && !env) return error("bound Java thread has no current JNIEnv");
    if(fn(env,nullptr,0,0,0,0,0,0,0)!=0x41524d3634425247ULL)
        return error("translated relay magic differs");
    memcpy(bound_path,path,strlen(path)+1);
    dispatch=fn;
#if defined(RR_MUMU_STANDALONE_TEST) || defined(RR_MUMU_ART_TEST)
    fixture_guest=guest;
    fixture_bridge=bridge;
#endif
    return 1;
}
extern "C" __attribute__((visibility("default")))
int rr_mumu_bind(const char* path) { return bind_impl(path,true); }
extern "C" __attribute__((visibility("default")))
int rr_mumu_bind_api(const char* path,uint64_t bridge,uint64_t initialized,uint64_t get_vms) {
    if(!bridge || !initialized || !get_vms) return error("verified borrowed ART APIs required");
    borrowed_vms=reinterpret_cast<GetVMs>(get_vms);
    return bind_impl(path,true,reinterpret_cast<Bridge*>(bridge),reinterpret_cast<bool(*)()>(initialized));
}
extern "C" __attribute__((visibility("default")))
uint64_t rr_mumu_call(uint64_t op,uint64_t address,uint64_t a,uint64_t b,uint64_t c,uint64_t d,uint64_t e) {
    if(!dispatch || op>5 || (op && !address)) { error("unbound relay or unsupported operation"); return 0; }
    JNIEnv* env=environment();
#ifndef RR_MUMU_STANDALONE_TEST
    if(!env) { error("translated calls require the bound Java thread's JNIEnv"); return 0; }
#endif
    return dispatch(env,nullptr,op,address,a,b,c,d,e);
}

#ifdef RR_MUMU_STANDALONE_TEST
#include <unistd.h>
static const char* test_shorty(void*,void*) { return "JJJJJJJJ"; }
static uint32_t test_count(void*,void*) { return 0; }
static uint32_t test_methods(void*,void*,void*,uint32_t) { return 0; }
extern "C" __attribute__((visibility("default"),noinline))
uint64_t rr_mumu_test_address(uint64_t kind) {
    auto address=reinterpret_cast<uint64_t(*)(void*,void*,uint64_t)>(
        fixture_bridge->trampoline(fixture_guest,"Java_RoyaleReplayBridge_testAddress","JJ",2));
    return address?address(nullptr,nullptr,kind):0;
}
extern "C" __attribute__((visibility("default"),noinline))
void rr_mumu_test_ready() { asm volatile("" ::: "memory"); }
int main(int argc,char** argv) {
    setvbuf(stdout,nullptr,_IONBF,0);
    if(argc!=3) return 2;
    auto* itf=static_cast<Bridge*>(dlsym(dlopen("/system/lib64/libnb.so",RTLD_NOW),"NativeBridgeItf"));
    if(!itf || itf->version!=6) return 3;
    RuntimeCallbacks callbacks{test_shorty,test_count,test_methods};
    if(!itf->initialize(&callbacks,argv[2],"arm64")) return 4;
    if(!itf->anonymousNamespace("libc.so:libdl.so:libm.so","/system/lib64/arm64:/system/lib64/arm64/nb")) return 5;
    if(!bind_impl(argv[1],false)) { fprintf(stderr,"%s\n",rr_mumu_error()); return 6; }
    printf("{\"bridge_version\":6,\"relay_magic\":%llu,\"uid\":%u,\"pid\":%u}\n",
        static_cast<unsigned long long>(rr_mumu_call(0,0,0,0,0,0,0)),getuid(),getpid());
    if(rr_mumu_call(1,rr_mumu_test_address(1),0,0,0,0,0)!=0xfedcba9876543210ULL) return 11;
    if(rr_mumu_call(2,rr_mumu_test_address(2),0,0,0,0,0)!=static_cast<uint64_t>(-7LL)) return 12;
    const uint64_t a=0x1122334455667788ULL,c=0x8877665544332211ULL,d=0xfedcba9876543210ULL,e=0x8000000100000001ULL;
    if(rr_mumu_call(3,rr_mumu_test_address(3),a,123456789,c,d,e)!=1) return 13;
    const uint64_t expected[5]={a,123456789,c,d,e};
    uint64_t data=rr_mumu_test_address(6);
    if(!data || memcmp(reinterpret_cast<void*>(data),expected,sizeof(expected))) return 14;
    if(rr_mumu_call(4,rr_mumu_test_address(4),data,0,0,0,0)!=1) return 15;
    const char* path="/data/local/tmp/royale_replay_probe/fixture.so";
    if(rr_mumu_call(5,rr_mumu_test_address(5),reinterpret_cast<uint64_t>(path),2,0,0,0)!=data) return 16;
    printf("{\"typed_calls\":5,\"wide_arguments\":true,\"shared_memory\":true,\"game_calls\":false}\n");
    rr_mumu_test_ready();
    // Give the debugger an explicitly owned, live process for transport tests.
    if(getenv("RR_MUMU_WAIT")) while(true) sleep(1);
    return 0;
}
#endif
