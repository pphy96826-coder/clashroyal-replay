#include <android/native_activity.h>
#include <android/log.h>
#include <stdio.h>
#include <string.h>
#ifndef RR_ART_TEST_ID
#define RR_ART_TEST_ID "unspecified"
#endif
extern "C" __attribute__((visibility("default")))
void ANativeActivity_onCreate(ANativeActivity* activity,void*,size_t) {
    __android_log_print(ANDROID_LOG_INFO,"RR_MUMU_PROBE","ARM64 NativeActivity created");
    const char* path="/data/user/0/org.codex.mumu.replayprobe/files/librr_mumu_art_host.so";
    JNIEnv* env=activity->env;
    jclass system=env->FindClass("java/lang/System");
    jmethodID load=system?env->GetStaticMethodID(system,"load","(Ljava/lang/String;)V"):nullptr;
    bool ok=false;
    if(load) {
        jstring value=env->NewStringUTF(path);
        env->CallStaticVoidMethod(system,load,value);
        ok=!env->ExceptionCheck();
        env->DeleteLocalRef(value);
    }
    if(env->ExceptionCheck()) { env->ExceptionDescribe();env->ExceptionClear(); }
    __android_log_print(ANDROID_LOG_INFO,"RR_MUMU_PROBE","x86_64 System.load completed: %d",ok);
    FILE* f=fopen("/data/user/0/org.codex.mumu.replayprobe/files/activity-result.json","w");
    if(f) { fprintf(f,"{\"host_library_loaded\":%s,\"game_calls\":false,\"run_id\":\"%s\"}\n",ok?"true":"false",RR_ART_TEST_ID);fclose(f); }
}
