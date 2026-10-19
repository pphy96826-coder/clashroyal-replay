#define RR_MUMU_ART_TEST
#include "mumu_bridge_host.cpp"
#include <jni.h>
#include <android/log.h>
#ifndef RR_ART_TEST_ID
#define RR_ART_TEST_ID "unspecified"
#endif

static void save(int stage) {
    FILE* f=fopen("/data/user/0/org.codex.mumu.replayprobe/files/host-result.json","w");
    if(f) {
        fprintf(f,"{\"ok\":%s,\"stage\":%d,\"art_initialized_bridge\":%s,\"game_calls\":false,\"run_id\":\"%s\"}\n",stage==4?"true":"false",stage,stage>=1?"true":"false",RR_ART_TEST_ID);fclose(f);
    }
    __android_log_print(ANDROID_LOG_INFO,"RR_MUMU_PROBE","x86_64 host stage %d: %s",stage,rr_mumu_error());
}

static uint64_t address(uint64_t kind) {
    auto getter=reinterpret_cast<uint64_t(*)(void*,void*,uint64_t)>(fixture_bridge->trampoline(fixture_guest,
        "Java_RoyaleReplayBridge_testAddress","JJ",2));
    return getter?getter(environment(),nullptr,kind):0;
}
extern "C" __attribute__((visibility("default")))
jint JNI_OnLoad(JavaVM*,void*) {
    const char* guest="/data/user/0/org.codex.mumu.replayprobe/files/librr_mumu_guest.so";
    int stage=0;
    save(stage);
    if(rr_mumu_bind(guest)) {
        stage=1;
        save(stage);
        const char* component="/data/user/0/org.codex.mumu.replayprobe/files/libmumu_fixture_component.so";
        uint64_t handle=rr_mumu_call(5,address(7),reinterpret_cast<uint64_t>(component),2,0,0,0);
        if(handle) {
            stage=2;
            save(stage);
            uint64_t function=address(9);
            if(function && rr_mumu_call(1,function,0,0,0,0,0)==0x11223344fedcba98ULL) {
                stage=3;
                save(stage);
                if(rr_mumu_call(4,address(8),handle,0,0,0,0)==0) stage=4;
            }
        }
    }
    save(stage);
    if(stage!=4) fprintf(stderr,"MuMu ART probe stage %d: %s\n",stage,rr_mumu_error());
    return JNI_VERSION_1_6;
}
