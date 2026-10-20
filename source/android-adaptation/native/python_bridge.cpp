#include <jni.h>
#include <Python.h>
#include <mutex>
#include <string>

static std::mutex parser_lock;
static bool initialized=false;
static std::string owned_home;

static void failure(JNIEnv* env,const char* message){env->ThrowNew(env->FindClass("java/io/IOException"),message);}

extern "C" JNIEXPORT jint JNICALL
Java_local_royale_replay_android_NativePython_run(JNIEnv* env,jclass,jstring home,jstring input,jstring output){
    std::lock_guard<std::mutex> lock(parser_lock);
    const char* h=env->GetStringUTFChars(home,nullptr);const char* i=env->GetStringUTFChars(input,nullptr);const char* o=env->GetStringUTFChars(output,nullptr);
    std::string runtime(h),source(i),destination(o);
    env->ReleaseStringUTFChars(home,h);env->ReleaseStringUTFChars(input,i);env->ReleaseStringUTFChars(output,o);
    if(!initialized){
        PyConfig config;PyConfig_InitIsolatedConfig(&config);
        config.install_signal_handlers=0;config.write_bytecode=0;config.site_import=0;config.safe_path=1;
        PyStatus status=PyConfig_SetBytesString(&config,&config.home,runtime.c_str());
        if(!PyStatus_Exception(status))status=Py_InitializeFromConfig(&config);
        PyConfig_Clear(&config);
        if(PyStatus_Exception(status)){failure(env,status.err_msg?status.err_msg:"embedded Python initialization failed");return -1;}
        initialized=true;owned_home=runtime;PyEval_SaveThread();
    }
    if(owned_home!=runtime){failure(env,"runtime generation changed; restart control app before parsing");return -1;}
    PyGILState_STATE gil=PyGILState_Ensure();
    PyObject* main=PyImport_AddModule("__main__");PyObject* globals=PyModule_GetDict(main);
    PyObject* paths[]={PyUnicode_DecodeFSDefault(runtime.c_str()),PyUnicode_DecodeFSDefault(source.c_str()),PyUnicode_DecodeFSDefault(destination.c_str())};
    const char* keys[]={"_replay_home","_replay_input","_replay_output"};
    bool okay=true;for(unsigned n=0;n<3;++n){if(!paths[n]||PyDict_SetItemString(globals,keys[n],paths[n]))okay=false;Py_XDECREF(paths[n]);}
    int code=-1;
    if(okay)code=PyRun_SimpleString(
        "import sys, pathlib\n"
        "_code = pathlib.Path(_replay_home) / 'app'\n"
        "if str(_code) not in sys.path: sys.path.insert(0, str(_code))\n"
        "import device_import\n"
        "device_import.run(pathlib.Path(_replay_input), pathlib.Path(_replay_output))\n");
    if(PyErr_Occurred())PyErr_Print();
    PyGILState_Release(gil);
    if(code)failure(env,"phone parser failed; inspect private import report");
    return code;
}
