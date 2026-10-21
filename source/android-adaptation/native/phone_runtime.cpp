// Own fixed-purpose CLI, not a shell or an arbitrary Python interpreter.
// Android packages extract this PIE as libphone_runtime.so to an executable
// native-library directory. Existing, explicitly granted su runs it locally.
#include <Python.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <sys/stat.h>
#include <unistd.h>

static std::string canonical(const char* value) {
    char* path=realpath(value,nullptr);
    if(!path) return {};
    std::string result(path);free(path);return result;
}
static bool below(const std::string& value,const std::string& root){return value.compare(0,root.size()+1,root+"/")==0;}

int main(int argc,char** argv){
    umask(0077);
    if(argc!=6 || (std::strcmp(argv[1],"import-source") && std::strcmp(argv[1],"prepare") && std::strcmp(argv[1],"check-tools") && std::strcmp(argv[1],"check-native-tools") && std::strcmp(argv[1],"build-component") && std::strcmp(argv[1],"play") && std::strcmp(argv[1],"recover") && std::strcmp(argv[1],"finish") && std::strcmp(argv[1],"release-preparation")) || getuid()!=0){std::fputs("fixed local replay command required\n",stderr);return 2;}
    bool source_only=!std::strcmp(argv[1],"import-source");
    bool native_tools=!std::strcmp(argv[1],"check-native-tools");
    bool tools=!std::strcmp(argv[1],"check-tools")||native_tools;
    bool build=!std::strcmp(argv[1],"build-component");
    bool play=!std::strcmp(argv[1],"play");
    bool recover=!std::strcmp(argv[1],"recover");
    bool finish=!std::strcmp(argv[1],"finish");
    bool release=!std::strcmp(argv[1],"release-preparation");
    // Android's two app-data views may be bind mounts, not symlinks. Use the
    // same /data/user/0 view returned by Context instead of comparing aliases.
    const std::string owner="/data/user/0/local.royale.replay.android";
    std::string app=canonical(owner.c_str()),home=canonical(argv[2]),source=canonical(argv[3]);
    // The destination must be a new directory under an already app-owned job.
    std::string destination(argv[4]);auto slash=destination.rfind('/');
    std::string parent=slash==std::string::npos?"":canonical(destination.substr(0,slash).c_str());
    std::string leaf=slash==std::string::npos?"":destination.substr(slash+1);
    struct stat state{};
    if(app.empty()||!below(home,app+"/files")||!below(source,app+"/files")||!below(parent,app+"/files")
       ||leaf!=(source_only?"result":tools?"tools-check":build?"native-build":play?"phone-playback":recover?"phone-recovery":finish?"phone-finish":release?"preparation-release":"native-preparation")||lstat(destination.c_str(),&state)==0
       ||(source_only&&(source!=parent+"/input.html"||std::strcmp(argv[5],"-")))
       ||((build||play||recover||finish||release)&&!below(canonical(argv[5]),app+"/files"))
       ||stat(parent.c_str(),&state)||state.st_uid<10000){std::fputs("invalid private preparation paths\n",stderr);return 2;}
    PyConfig config;PyConfig_InitIsolatedConfig(&config);
    config.install_signal_handlers=0;config.write_bytecode=0;config.site_import=0;config.safe_path=1;
    PyStatus status=PyConfig_SetBytesString(&config,&config.home,home.c_str());
#ifdef RR_MUMU_NATIVE_X86
    // Native x86 tools must load native extension modules, never the ARM
    // interpreter's lib-dynload directory. Pure Python sources stay identical.
    config.module_search_paths_set=1;
    for(const auto& path:{home+"/app/mumu-support/runtime/lib/python3.14",home+"/lib/python3.14",home+"/app/mumu-support/runtime/lib/python3.14/lib-dynload"}){
        wchar_t* wide=Py_DecodeLocale(path.c_str(),nullptr);
        if(!wide){PyConfig_Clear(&config);return 3;}
        if(!PyStatus_Exception(status))status=PyWideStringList_Append(&config.module_search_paths,wide);
        PyMem_RawFree(wide);
    }
#endif
    if(!PyStatus_Exception(status))status=Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if(PyStatus_Exception(status)){std::fprintf(stderr,"local Python initialization failed: %s\n",status.err_msg?status.err_msg:"unknown initialization error");return 3;}
    PyObject* globals=PyModule_GetDict(PyImport_AddModule("__main__"));
    const char* keys[]={"_home","_source","_output","_apk"};
    const char* values[]={home.c_str(),source.c_str(),destination.c_str(),argv[5]};
    for(unsigned n=0;n<4;++n){PyObject* value=PyUnicode_DecodeFSDefault(values[n]);if(!value||PyDict_SetItemString(globals,keys[n],value)){Py_XDECREF(value);return 3;}Py_DECREF(value);}
    int result=PyRun_SimpleString(source_only?
        "import sys,os\nfrom pathlib import Path\nsys.path.insert(0, str(Path(_home)/'app'))\nimport device_import\ntry:\n device_import.run(Path(_source), Path(_output))\nfinally:\n owner=Path(_source).parent.stat()\n for item in [Path(_output),*Path(_output).rglob('*')]:\n  if item.is_symlink(): raise ValueError('unexpected source output link')\n  os.chown(item,owner.st_uid,owner.st_gid)\n":
        native_tools?
        "import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(_home)/'app'))\nimport native_runtime_check\nnative_runtime_check.run(Path(_source), Path(_output))\n":
        tools?
        "import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(_home)/'app'))\nimport device_tools\ndevice_tools.run(Path(_source), Path(_output))\n":
        release?"import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(_home)/'app'))\nimport device_playback\ndevice_playback.release_preparation(Path(_source), Path(_output), Path(_apk))\n":
        recover?"import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(_home)/'app'))\nimport device_recovery\ndevice_recovery.run(Path(_source), Path(_output), Path(_apk))\n":
        finish?"import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(_home)/'app'))\nimport device_playback\ndevice_playback.finish_completed(Path(_source), Path(_output), Path(_apk))\n":
        play?"import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(_home)/'app'))\nimport device_playback\ndevice_playback.run(Path(_source), Path(_output), Path(_apk))\n":
        build?"import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(_home)/'app'))\nimport device_build\ndevice_build.run(Path(_source), Path(_output), Path(_apk))\n":
        "import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(_home)/'app'))\nimport device_metadata\ndevice_metadata.run(Path(_source), Path(_output), Path(_apk))\n");
    if(PyErr_Occurred())PyErr_Print();
    return result?4:0;
}
