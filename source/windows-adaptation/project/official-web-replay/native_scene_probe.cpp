// Canonical local ReplayManager entry; normal client frames own/render playback.
// Private CSV/Layout cache lease stays alive until BOTH native controllers have
// released the replay Domain. Never frees or overwrites borrowed lobby objects.
#include "../offline-private-map/build/assets.h"
#include "../runtime-audit-20261014-direct-route-v12/build/runtime_probe.cpp"
#include WEB_SCENE_BINDINGS
#include WEB_SCENE_INPUT
#include "cache_lease.h"
#include "source_execution.h"
#include "replay_frame_clock.h"
#include "native_tower_check.h"
#include <atomic>
#include <new>

namespace {
struct SceneProbe {
    uintptr_t base,services,root,manager,initial_controller;uint64_t tid;
    uintptr_t csv[2]{},replay_controller{};replay_cache::Lease lease;
    std::atomic<unsigned> entered{0},returned{0},destroyed{0};
    unsigned cleanup_entered{},cleanup_done{},stage{},failure{},published{};
    uintptr_t controller_table[130]{};
    unsigned driver_bound{},driver_error{},driver_frames{},terminal_tick{};
    unsigned presentation_frames{},presentation_handle{};
    uintptr_t presentation{};
    float accumulator{};
    web_source::Result trace;
    std::string trace_text;
    uint64_t fields[48]{};
    SceneProbe(uintptr_t b,uintptr_t s,uintptr_t r,uintptr_t m,uintptr_t c,uint64_t t):
        base(b),services(s),root(r),manager(m),initial_controller(c),tid(t){}
};
SceneProbe* state{};
bool readable(uintptr_t p,size_t n){return mapped(p&0x00ffffffffffffffULL,n,"r");}
bool stable(void* v){auto* p=static_cast<SceneProbe*>(v);
    return read<uintptr_t>(p->base+0x1d34ae0)==p->root&&readable(p->root,0x28)&&
           read<uintptr_t>(p->root+0x20)==p->services&&read<uintptr_t>(p->base+0x1d46bd0)==p->manager;
}
bool pins(uintptr_t b){
    if(b!=scene_base)return false;
    for(const auto& p:scene_pins)if(!mapped(b+p.va,p.size,"rx")||std::memcmp(reinterpret_cast<void*>(b+p.va),p.bytes,p.size))return false;
    return true;
}
replay_cache::Calls lease_calls(SceneProbe* p){auto b=p->base;
    return {readable,stable,p,reinterpret_cast<void(*)(void*,void*,void*,int)>(b+0x1052df0),
        reinterpret_cast<void(*)(void*)>(b+0x10da3b8),reinterpret_cast<void(*)(void*)>(b+0x1b34940),
        reinterpret_cast<void(*)(void*)>(b+0x16cb3c8),reinterpret_cast<void(*)(void*)>(b+0x1b34938)};
}
bool lobby_controller(SceneProbe* p,uintptr_t controller){
    if(!readable(controller,0x98)||read<uintptr_t>(controller)!=p->base+0x1bebd08||
       read<int>(controller+0x58)!=0||read<int>(controller+0x30)!=9)return false;
    auto domain=read<uintptr_t>(controller+0x90);
    return readable(domain,0xb0)&&read<int>(domain+0x20)==1&&!read<uintptr_t>(domain+0xa8);
}
bool bind_source_trace(SceneProbe* p,uintptr_t domain,uintptr_t battle){
    if(!native_towers_match(p->base,domain,battle,scene_towers,scene_support,readable))return false;
    web_source::ReadRanges ranges;if(!ranges.refresh())return false;
    auto within=[&](uintptr_t address,size_t size){return ranges.contains(address,size);};
    for(unsigned side=0;side<2;++side){
        auto id=read<uintptr_t>(battle+0x30+side*8);
        if(!within(id,8)||read<unsigned>(id)!=scene_identities[side][0]||read<unsigned>(id+4)!=scene_identities[side][1])return false;
    }
    auto queue=read<uintptr_t>(domain+0x38);constexpr size_t count=sizeof(scene_events)/sizeof(scene_events[0]);
    if(!within(queue,0x28)||read<int>(queue+0x14)!=count)return false;
    auto commands=read<uintptr_t>(queue+8);if(!within(commands,count*8))return false;
    web_source::current_ranges=&ranges;
    web_source::Calls calls{p->base,p->services,web_source::bounded_read,stable,p};
    web_source::active_trace=&p->trace;web_source::active_base=p->base;
    bool okay=true;
    for(size_t i=0;i<count;++i){
        auto command=read<uintptr_t>(commands+i*8);const auto& event=scene_events[i];
        if(!within(command,event.kind==153?88:56)||read<uintptr_t>(command)!=p->base+(event.kind==153?0x1bf6260:0x1bf69b0)||
           read<int>(command+0xc)!=event.tick||read<int>(command+0x10)!=event.tick){okay=false;break;}
        p->trace.event_index=i;
        if(!web_source::trace_command(calls,p->trace,reinterpret_cast<void*>(command),event.kind)){okay=false;break;}
    }
    web_source::current_ranges=nullptr;return okay;
}
// Local replay driver, installed ONLY on the controller created by this
// request. Native command validation/execution and native renderer stay intact.
// Unlike the general client controller frame (ECC5BC/ECCC94), this driver does
// not construct session command/checksum reports or invoke their message sinks.
// No shared function, global vtable, transport, server check or network setting
// is patched. Lobby/online controllers continue using their original table.
void local_frame(void* object,float elapsed){
    auto* p=state;auto controller=reinterpret_cast<uintptr_t>(object);
    if(!p||controller!=p->replay_controller||p->driver_error)return;
    if(cr_noop_current_tid()!=p->tid||!stable(p)||read<uintptr_t>(controller)!=reinterpret_cast<uintptr_t>(p->controller_table+2)||
       read<int>(controller+0x58)!=1||read<int>(controller+0x30)!=9){p->driver_error=1;return;}
    auto d=read<uintptr_t>(controller+0x90),scene=read<uintptr_t>(controller+0x50);
    if(!d||!scene||read<int>(d+0x20)!=4||read<uintptr_t>(scene)!=p->base+0x1bd3cb0){p->driver_error=2;return;}
    auto battle=read<uintptr_t>(d+0xa8);if(!battle){p->driver_error=3;return;}
    if(!p->driver_bound){
        if(read<int>(d+0x60)!=0||!bind_source_trace(p,d,battle)){p->driver_error=4;return;}
        p->driver_bound=1;
    }
    float delta{};
    if(!replay_frame_clock::bounded_delta(elapsed,delta)){p->driver_error=5;return;}
    float speed=read<float>(controller+0x74);
    if(!replay_frame_clock::valid_rate(speed)){p->driver_error=6;return;}
    if(read<unsigned char>(controller+0x17c))delta=0; // Native pause state.
    p->accumulator+=delta*speed;
    auto finished=[&](){return reinterpret_cast<int(*)(void*)>(p->base+0xf5603c)(reinterpret_cast<void*>(battle));};
    unsigned steps=0;
    while(p->accumulator>=.05f&&!finished()){
        auto before=read<int>(d+0x60);
        reinterpret_cast<int(*)(void*)>(p->base+0x1366f64)(reinterpret_cast<void*>(d));
        if(read<int>(d+0x60)!=before+1||++steps>10){p->driver_error=7;return;}
        p->accumulator-=.05f;
    }
    if(finished()&&!p->terminal_tick)p->terminal_tick=read<int>(d+0x60);
    for(const auto& entry:p->trace.dispatch)if(entry.code!=-10000&&entry.code!=0){p->driver_error=8;return;}
    // ECC914/ECC92C updates the separately registered battlefield presentation
    // BEFORE the scene/HUD callback. Without it the native battle progresses
    // but the arena and unit geometry remain black. Keep the original native
    // handle lookup, delta, and fixed-tick interpolation arguments.
    auto handle=read<int>(controller+0x2b0);
    if(handle<1){p->driver_error=12;return;}
    auto registry=reinterpret_cast<void*(*)()>(p->base+0x8d9460)();
    auto presentation=reinterpret_cast<void*(*)(void*,int)>(p->base+0x8d9738)(registry,handle);
    auto address=reinterpret_cast<uintptr_t>(presentation);
    if(!readable(address,0x220)||read<int>(address+0x1f0)!=handle){p->driver_error=13;return;}
    float alpha=p->accumulator*20.f;
    if(alpha<0)alpha=0;if(alpha>1)alpha=1;
    reinterpret_cast<void(*)(void*,float,float)>(p->base+0x8d6bc4)(presentation,delta*speed,alpha);
    p->presentation=address;p->presentation_handle=handle;++p->presentation_frames;
    // Terminal observers already received the last real native tick. The
    // generic scene end workflow can request a session pause/report; preserve
    // the terminal battlefield instead of entering that online result workflow.
    if(!p->terminal_tick)reinterpret_cast<void(*)(void*,float,float)>(p->base+scene_frame_va)(reinterpret_cast<void*>(scene),delta*speed,delta);
    // Generic frame ECC9EC separately advances the display tree at C+38.
    // Scene logic/UI alone does not advance its native graphical objects.
    auto display=read<uintptr_t>(controller+0x38);
    if(!display||read<uintptr_t>(display)!=p->base+0x1b4f558||
       read<uintptr_t>(p->base+0x1b4f558+0x168)!=p->base+0x9a7b54){p->driver_error=11;return;}
    reinterpret_cast<void(*)(void*,float)>(p->base+0x9a7b54)(reinterpret_cast<void*>(display),delta);
    ++p->driver_frames;
}
void local_render(void* object,float elapsed){
    auto* p=state;auto controller=reinterpret_cast<uintptr_t>(object);
    if(!p||controller!=p->replay_controller||p->driver_error||!p->driver_bound)return;
    float delta{};
    if(cr_noop_current_tid()!=p->tid||!stable(p)||!replay_frame_clock::bounded_delta(elapsed,delta)){p->driver_error=9;return;}
    auto scene=read<uintptr_t>(controller+0x50);
    if(!scene||read<uintptr_t>(scene)!=p->base+0x1bd3cb0){p->driver_error=10;return;}
    // Slot78 is a separate render pump. Its native implementation ECD640 also
    // calls the session-reporting stepper; use only its original scene callback.
    reinterpret_cast<void(*)(void*,float)>(p->base+scene_interpolate_va)(reinterpret_cast<void*>(scene),delta);
}
bool initialize(SceneProbe* p){auto b=p->base;
    if(!stable(p)||!pins(b)||read<uintptr_t>(p->manager+0x28)!=p->initial_controller||
       !lobby_controller(p,p->initial_controller)||read<int>(p->manager+0x3c)||
       read<uintptr_t>(p->manager+0x20)||read<uintptr_t>(p->manager+0x88)){
        p->failure=1;return false;
    }
    // The source's level16 default towers and cache generation must be ready.
    auto support=read<uintptr_t>(p->services+0xc70);
    if(!readable(support,0xb0)||read<int>(support+0x40)!=169000000||!read<uintptr_t>(support+0xa8)){
        p->failure=2;return false;
    }
    p->stage=1;
    const char* names[]={"locations/dragon_arena.csv","tilemaps/tilemap.csv"};
    const char* assets[]={asset_0,asset_1};int sizes[]={asset_0_size,asset_1_size};
    for(unsigned i=0;i<2;++i){
        auto object=malloc(0x68);if(!object){p->failure=3;return false;}
        std::memset(object,0,0x68);p->csv[i]=reinterpret_cast<uintptr_t>(object);
        alignas(16) unsigned char name[16]{};
        reinterpret_cast<void(*)(void*,const char*)>(b+0x16cb4d8)(name,names[i]);
        reinterpret_cast<void(*)(void*,const char*,int,void*)>(b+0x152cd44)(object,assets[i],sizes[i],name);
        reinterpret_cast<void(*)(void*)>(b+0x16cb3c8)(name);
    }
    p->stage=2;auto calls=lease_calls(p);
    if(!replay_cache::acquire(calls,p->lease,p->services,reinterpret_cast<void*>(p->csv[0]),
                            reinterpret_cast<void*>(p->csv[1]),36,64)){
        p->failure=4;return false;
    }
    p->stage=3;
    void* text=malloc(16);if(!text){p->failure=5;return false;}
    reinterpret_cast<void(*)(void*,const char*)>(b+0x16cb4d8)(text,scene_json);
    // Canonical setter consumes/destroys the heap NativeString and owns parsed
    // JSON. It requests controller4 (local replay); NOT a matchmaking/network API.
    reinterpret_cast<void(*)(void*,void*)>(b+0xed2438)(reinterpret_cast<void*>(p->manager),text);
    p->published=1;p->stage=4;
    if(!read<uintptr_t>(p->manager+0x88)||read<int>(p->manager+0x3c)!=4||read<int>(p->manager+0x14)!=3){
        p->failure=6;return false;
    }
    // Complete the canonical controller replacement on the native worker,
    // before its first rendered frame can enter generic session reporting.
    reinterpret_cast<void(*)(void*)>(b+0xed22b4)(reinterpret_cast<void*>(p->manager));
    auto controller=read<uintptr_t>(p->manager+0x28);
    if(!readable(controller,0x2d0)||read<uintptr_t>(controller)!=b+0x1bebd08||
       read<int>(controller+0x58)!=1||read<uintptr_t>(b+0x1bebd08+0x68)!=b+0xecc5bc||
       read<uintptr_t>(b+0x1bebd08+0x78)!=b+0xecd640){p->failure=7;return false;}
    std::memcpy(p->controller_table,reinterpret_cast<void*>(b+0x1bebd08-16),sizeof(p->controller_table));
    p->controller_table[2+0x68/8]=reinterpret_cast<uintptr_t>(local_frame);
    p->controller_table[2+0x78/8]=reinterpret_cast<uintptr_t>(local_render);
    auto own_table=reinterpret_cast<uintptr_t>(p->controller_table+2);
    std::memcpy(reinterpret_cast<void*>(controller),&own_table,8);
    // Presentation speed is a private replay-controller setting. Source ticks,
    // card positions, queue order and native simulation delta stay unchanged.
    std::memcpy(reinterpret_cast<void*>(controller+0x74),&scene_initial_speed,sizeof(float));
    p->replay_controller=controller;p->stage=6;
    return true;
}
bool cleanup(SceneProbe* p){
    p->cleanup_entered++;
    if(!stable(p)||!pins(p->base)){p->failure=20;return false;}
    // A rejected precondition never acquired resources or a replay controller.
    // Release only this component's observation state; don't touch the foreign
    // battle that caused rejection.
    if(!p->published&&!p->replay_controller&&!p->csv[0]&&!p->csv[1]&&!p->lease.stage){
        p->failure=0;p->cleanup_done=1;p->stage=7;return true;
    }
    auto primary=read<uintptr_t>(p->manager+0x28),auxiliary=read<uintptr_t>(p->manager+0x20);
    // Keep resource owners while either controller/fade can still reference
    // the replay graph. Never manually clear a client controller or Domain.
    if(!lobby_controller(p,primary)||auxiliary||read<int>(p->manager+0x3c))return false;
    auto calls=lease_calls(p);
    if(!replay_cache::release(calls,p->lease,true)){p->failure=21;return false;}
    for(unsigned i=0;i<2;++i){
        reinterpret_cast<void(*)(void*)>(p->base+0x152ceec)(reinterpret_cast<void*>(p->csv[i]));
        reinterpret_cast<void(*)(void*)>(p->base+0x1b34938)(reinterpret_cast<void*>(p->csv[i]));p->csv[i]=0;
    }
    web_source::active_trace=nullptr;
    p->cleanup_done=1;p->stage=7;return true;
}
struct Task;using Method=void(*)(Task*)noexcept;struct Task{const Method* methods;SceneProbe* p;bool clean;};
void destroy(Task* t)noexcept{if(t->p)t->p->destroyed.store(1,std::memory_order_release);t->p=nullptr;}
void remove(Task* t)noexcept{destroy(t);delete t;}
void execute(Task* t)noexcept{auto* p=t->p;if(!p)return;p->entered=1;
    if(cr_noop_current_tid()!=p->tid||!stable(p)||!pins(p->base))p->failure=30;
    else if(t->clean)cleanup(p);else initialize(p);
    p->returned.store(1,std::memory_order_release);
}
const Method methods[]={destroy,remove,execute};
int publish(SceneProbe* p,bool clean){
    auto* task=new(std::nothrow)Task{methods,p,clean};if(!task)return -4;
    p->entered=0;p->returned=0;p->destroyed=0;
    EmptyBinding binding{reinterpret_cast<unsigned char*>(p->base+0x1d88818)};
    if(!publish_empty(&binding,reinterpret_cast<CrNoopTask*>(task))){remove(task);return -10+binding.result;}
    return 1;
}
}
EXPORT int cr_web_scene_start(uintptr_t b,int pid,uint64_t tid,uintptr_t handle,uintptr_t services){
    if(state||!validated(b,pid,tid,handle)||!pins(b))return -1;
    auto root=read<uintptr_t>(b+0x1d34ae0),manager=read<uintptr_t>(b+0x1d46bd0);
    if(!readable(root,0x28)||read<uintptr_t>(root+0x20)!=services||!readable(manager,0xa0))return -2;
    auto controller=read<uintptr_t>(manager+0x28);
    state=new(std::nothrow)SceneProbe{b,services,root,manager,controller,tid};if(!state)return -3;
    return publish(state,false);
}
EXPORT int cr_web_scene_cleanup(){return state&&state->destroyed?publish(state,true):0;}
EXPORT uintptr_t cr_web_scene_done_address(){return state?reinterpret_cast<uintptr_t>(&state->destroyed):0;}
EXPORT uintptr_t cr_web_scene_result_address(){
    if(!state)return 0;auto* p=state;auto& f=p->fields;
    f[0]=p->entered;f[1]=p->returned;f[2]=p->destroyed;f[3]=p->stage;f[4]=p->failure;
    f[5]=p->published;f[6]=p->cleanup_entered;f[7]=p->cleanup_done;
    f[8]=p->manager;f[9]=p->initial_controller;f[10]=p->csv[0];f[11]=p->csv[1];
    f[12]=p->lease.stage;f[13]=p->lease.failure;f[14]=p->lease.layout;
    if(stable(p)){
        auto controller=read<uintptr_t>(p->manager+0x28);f[15]=controller;f[16]=read<uintptr_t>(p->manager+0x20);
        f[17]=read<int>(p->manager+0x14);f[18]=read<int>(p->manager+0x3c);f[19]=read<uintptr_t>(p->manager+0x88);
        if(readable(controller,0x98)&&(read<uintptr_t>(controller)==p->base+0x1bebd08||
           (controller==p->replay_controller&&read<uintptr_t>(controller)==reinterpret_cast<uintptr_t>(p->controller_table+2)))){
            f[20]=read<int>(controller+0x58);f[21]=read<int>(controller+0x30);f[22]=read<uintptr_t>(controller+0x50);
            auto domain=read<uintptr_t>(controller+0x90);f[23]=domain;
            if(readable(domain,0xb0)){f[24]=read<int>(domain+0x20);f[25]=read<int>(domain+0x60);f[26]=read<uintptr_t>(domain+0xa8);}
        }
    }
    f[27]=p->replay_controller;f[28]=p->driver_bound;f[29]=p->driver_error;f[30]=p->driver_frames;f[31]=p->terminal_tick;
    f[32]=p->presentation_frames;f[33]=p->presentation_handle;f[34]=p->presentation;
    if(stable(p)&&read<uintptr_t>(p->manager+0x28)==p->replay_controller&&p->replay_controller){
        f[35]=read<unsigned>(p->replay_controller+0x74);
        f[36]=read<unsigned char>(p->replay_controller+0x17c);
    }
    return reinterpret_cast<uintptr_t>(f);
}
EXPORT uintptr_t cr_web_scene_trace_address(){
    if(!state)return 0;auto* p=state;p->trace_text="[";
    for(const auto& entry:p->trace.dispatch){
        if(p->trace_text.size()>1)p->trace_text+=',';
        p->trace_text+="{\"index\":"+std::to_string(entry.index)+",\"kind\":"+std::to_string(entry.kind)+",\"tick\":"+std::to_string(entry.tick)+",\"flags\":"+std::to_string(entry.flags)+",\"code\":"+std::to_string(entry.code)+'}';
    }
    p->trace_text+=']';return reinterpret_cast<uintptr_t>(p->trace_text.data());
}
EXPORT uintptr_t cr_web_scene_trace_size(){return state?state->trace_text.size():0;}
EXPORT int cr_web_scene_release(){
    if(!state||!state->destroyed||!state->cleanup_done||state->lease.layout||state->csv[0]||state->csv[1])return 0;
    delete state;state=nullptr;return 1;
}
