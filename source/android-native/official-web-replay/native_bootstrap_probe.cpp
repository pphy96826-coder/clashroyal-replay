// Initialization-only verification. Never touches the lobby Domain or changes
// ReplayManager. This must pass before publishing a source replay to native UI.
#include "../offline-private-layout/layout_cycle.h"
#include "../offline-private-map/build/assets.h"
#include "../offline-private-layout/build/objects.h"
#include "../runtime-audit-20261014-direct-route-v12/build/runtime_probe.cpp"
#ifndef WEB_BOOTSTRAP_BINDINGS
#define WEB_BOOTSTRAP_BINDINGS "build/bootstrap_bindings.h"
#define WEB_BOOTSTRAP_INPUT "build/bootstrap_input.h"
#endif
#include WEB_BOOTSTRAP_BINDINGS
#include WEB_BOOTSTRAP_INPUT
#include "cache_lease.h"
#include "source_execution.h"
#include "native_tower_check.h"
#include <new>

namespace {
struct Probe {
    uintptr_t base,services,root;uint64_t tid;
    std::atomic<unsigned> entered{0},returned{0},destroyed{0};
    uint64_t fields[96]{};
    uint64_t towers[48]{};
    private_layout::Result layout;
    uintptr_t domain{},json{};
    bool resource_preflight_rejected{};
    replay_cache::Lease cache_lease;
    web_source::Result source;
    Probe(uintptr_t b,uintptr_t s,uintptr_t r,uint64_t t):base(b),services(s),root(r),tid(t){}
};
Probe* probe{};
bool readable(uintptr_t p,size_t n){return mapped(p&0x00ffffffffffffffULL,n,"rw");}
bool source_readable(uintptr_t p,size_t n){return mapped(p&0x00ffffffffffffffULL,n,"r");}
bool stable(void* v){auto* p=static_cast<Probe*>(v);
    return read<uintptr_t>(p->base+0x1d34ae0)==p->root && readable(p->root,0x28) &&
        read<uintptr_t>(p->root+0x20)==p->services;}
bool check_pins(uintptr_t b){
    if(b!=bootstrap_base)return false;
    for(const auto& p:bootstrap_pins)
        if(!mapped(b+p.va,p.size,"rx")||std::memcmp(reinterpret_cast<void*>(b+p.va),p.bytes,p.size))return false;
    return true;
}
bool location_cache_empty_ready(Probe* p){
    // 1090a7c -> Services layout vector +13d8, indexed by the category15
    // Location ID remainder. A separately allocated Layout is NOT this cache.
    if(!readable(p->services,0x13e8))return false;
    auto registry=read<uintptr_t>(p->services+0x78);
    if(!readable(registry,0x88)||read<int>(registry+0x84)!=15)return false;
    int count=read<int>(registry+0x3c),capacity=read<int>(registry+0x38);
    auto entries=read<uintptr_t>(registry+0x30);
    if(count<=61||count>capacity||capacity>1024||!readable(entries,62*8))return false;
    auto location=read<uintptr_t>(entries+61*8);
    if(!readable(location,0x48)||read<int>(location+0x40)!=15000061||
       read<uintptr_t>(location+0x10)!=registry)return false;
    auto cache=read<uintptr_t>(p->services+0x13d8);
    count=read<int>(p->services+0x13e4);capacity=read<int>(p->services+0x13e0);
    if(count<=61||count>capacity||capacity>512||!readable(cache,62*8))return false;
    return read<uintptr_t>(cache+61*8)==0;
}
bool default_towers_ready(Probe* p){
    auto support=read<uintptr_t>(p->services+0xc70);
    if(!readable(support,0xb8)||read<int>(support+0x40)!=169000000||!read<uintptr_t>(support+0xa0))return false;
    auto group=read<uintptr_t>(support+0xa8);
    if(!readable(group,0xa0)||read<int>(group+0x9c)!=3)return false;
    auto elements=read<uintptr_t>(group+0x90);
    if(!readable(elements,24))return false;
    unsigned kings=0,princesses=0;
    for(unsigned i=0;i<3;++i){
        auto item=read<uintptr_t>(elements+i*8);if(!readable(item,32))return false;
        auto definition=read<uintptr_t>(item+8);if(!readable(definition,0x584))return false;
        int id=read<int>(definition+0x40);
        if(id==35000000)kings++;else if(id==35000001)princesses++;else return false;
    }
    return kings==1&&princesses==2;
}
void* lookup(unsigned category,void* name){
    auto* p=probe;if(!p||!stable(p)||(category!=97&&category!=6))return nullptr;
    auto registry=read<uintptr_t>(p->services+category*8);
    if(!readable(registry,0x88))return nullptr;
    auto table=read<uintptr_t>(registry);
    if(!mapped(table,0x50,"r"))return nullptr;
    auto fn=read<uintptr_t>(table+0x48);
    if(fn!=p->base+bootstrap_lookup_va&&fn!=p->base+0x103864c)return nullptr;
    return reinterpret_cast<void*(*)(void*,void*)>(fn)(reinterpret_cast<void*>(registry),name);
}
bool consume(void* v,void* layout){
    auto* p=static_cast<Probe*>(v);auto b=p->base;auto& f=p->fields;
    (void)layout;
    replay_cache::Calls cache{readable,stable,p,
        reinterpret_cast<void(*)(void*,void*,void*,int)>(b+0x1052df0),
        reinterpret_cast<void(*)(void*)>(b+0x10da3b8),
        reinterpret_cast<void(*)(void*)>(b+0x1b34940),
        reinterpret_cast<void(*)(void*)>(b+0x16cb3c8),
        reinterpret_cast<void(*)(void*)>(b+0x1b34938)};
    if(!replay_cache::acquire(cache,p->cache_lease,p->services,
        reinterpret_cast<void*>(p->layout.owned_csv0.load()),
        reinterpret_cast<void*>(p->layout.owned_csv1.load()),map_width,map_height)){
        f[4]=31;return false;
    }
    alignas(16) unsigned char string[16]{};
    reinterpret_cast<void(*)(void*,const char*)>(b+0x16cb4d8)(string,bootstrap_json);
    auto json=reinterpret_cast<void*(*)(void*,int,int)>(b+0x1537d58)(string,0,100);
    p->json=reinterpret_cast<uintptr_t>(json);
    reinterpret_cast<void(*)(void*)>(b+0x16cb3c8)(string);
    if(!json){f[4]=1;return false;}
    void* domain=malloc(0x240);if(!domain){f[4]=2;return false;}
    p->domain=reinterpret_cast<uintptr_t>(domain);std::memset(domain,0,0x240);
    reinterpret_cast<void*(*)(void*,int,void*,void*,int)>(b+0x1365bf0)(domain,1,
        reinterpret_cast<void*>(p->services),reinterpret_cast<void*>(b+0x1c75240),0);
    auto d=p->domain;f[5]=read<int>(d+0x20);
    auto empty_owner=read<uintptr_t>(d+0xb0);
    if(f[5]!=0||!readable(empty_owner,8)||empty_owner!=read<uintptr_t>(d+0xc0)){
        f[4]=3;return false;
    }
    bool loaded=reinterpret_cast<bool(*)(void*,void*,void*,void*)>(b+0x1366bb4)(
        domain,json,nullptr,reinterpret_cast<void*>(empty_owner));
    f[6]=loaded;f[7]=read<int>(d+0x20);f[8]=read<int>(d+0x60);
    if(!loaded){f[4]=4;return false;}
    auto battle=read<uintptr_t>(d+0xa8);
    if(!readable(battle,0x440)){f[4]=5;return false;}
    f[9]=1;
    // Only for a fully loaded private Domain. Caller may use this after the
    // read-only deal assertions below; never for a pending/partial parser.
    auto release_loaded=[&](){
        reinterpret_cast<void(*)(void*)>(b+0x1366114)(domain);f[12]=1;
        for(size_t off:{size_t(0x18),size_t(0x38),size_t(0x40),size_t(0xa8),size_t(0xb0),size_t(0xc0)})
            if(read<uintptr_t>(d+off)){f[4]=12;return false;}
        reinterpret_cast<void(*)(void*)>(b+0xabea80)(domain);
        reinterpret_cast<void(*)(void*)>(b+0x1b34938)(domain);p->domain=0;f[13]=1;
        auto table=read<uintptr_t>(p->json);
        reinterpret_cast<void(*)(void*)>(read<uintptr_t>(table+8))(json);p->json=0;f[14]=1;
        if(!replay_cache::release(cache,p->cache_lease,!p->domain&&!p->json)){f[4]=32;return false;}
        return stable(p);
    };
    // Distinct IDs are mandatory: otherwise native participant lookup can
    // select the other side's avatar/deck even when physical card rows parse.
    for(unsigned side=0;side<2;++side){
        auto identity=read<uintptr_t>(battle+0x30+side*8);
        if(!readable(identity,8)||read<unsigned>(identity)!=bootstrap_identities[side][0]||
           read<unsigned>(identity+4)!=bootstrap_identities[side][1]){f[4]=45;return false;}
    }
    auto metadata=read<uintptr_t>(battle+0x2e8);
    if(!readable(metadata,16)){f[4]=6;return false;}
    f[10]=read<unsigned>(metadata+12);
    // Read only private decoded cards. No account or lobby card objects.
    for(unsigned side=0;side<2;++side){
        auto deck=read<uintptr_t>(battle+0x88+side*8);
        if(!readable(deck,0x58)||read<int>(deck+0x2c)!=8){f[4]=7;return false;}
        auto cards=read<uintptr_t>(deck+0x20);
        if(!readable(cards,64)){f[4]=8;return false;}
        for(unsigned i=0;i<8;++i){
            auto card=read<uintptr_t>(cards+i*8);
            if(!readable(card,0x50)){f[4]=9;return false;}
            auto definition=read<uintptr_t>(card+0x10);
            if(!readable(definition,0x48)){f[4]=10;return false;}
            auto k=16+(side*8+i)*4;
            f[k]=read<unsigned>(definition+0x40);f[k+1]=read<int>(card+0x18);
            f[k+2]=read<unsigned>(card+0x1c);f[k+3]=read<unsigned>(card+0x24);
            if(f[k]!=bootstrap_cards[side][i][0]||f[k+1]!=bootstrap_cards[side][i][1]||
               f[k+2]!=bootstrap_cards[side][i][2]){f[4]=11;return false;}
        }
    }
    f[11]=1;
    if(!native_towers_match(b,d,battle,bootstrap_towers,bootstrap_support,readable,p->towers)){
        f[93]++;f[4]=39;return false;
    }
    f[15]=6;
    for(unsigned i=0;i<6;++i){if(p->towers[i*8+7])f[91]++;else f[92]++;}
    if(f[91]!=2||f[92]!=4){f[4]=40;return false;}
    // Capture the ACTUAL native deal, not a Python shuffle or assumed opening.
    // Eight bytes per side: four hand indices followed by four queue indices.
    for(unsigned side=0;side<2;++side){
        auto root=read<uintptr_t>(battle+0xe0+side*8);
        if(!readable(root,0x418)||read<int>(root+0x224)!=4||read<int>(root+0x234)!=4){f[4]=41;return release_loaded();}
        auto hand=read<uintptr_t>(root+0x218),queue=read<uintptr_t>(root+0x228);
        if(!readable(hand,16)||!readable(queue,16)){f[4]=42;return release_loaded();}
        unsigned seen=0;uint64_t packed=0;
        for(unsigned i=0;i<8;++i){
            int index=read<int>((i<4?hand:queue)+(i%4)*4);
            if(index<0||index>=8||(seen&(1u<<index))){f[4]=43;return release_loaded();}
            seen|=1u<<index;packed|=uint64_t(index)<<(i*8);
        }
        f[94+side]=packed;
        if(bootstrap_run_source){
            auto deck=read<uintptr_t>(battle+0x88+side*8),cards=read<uintptr_t>(deck+0x20);
            for(unsigned i=0;i<8;++i){
                auto card=read<uintptr_t>(cards+((packed>>(i*8))&255)*8);
                auto definition=read<uintptr_t>(card+0x10);
                if(read<unsigned>(definition+0x40)!=bootstrap_desired_deal[side][i]){f[4]=44;return release_loaded();}
            }
        }
    }
    if(bootstrap_run_source){
        for(unsigned o=0;o<2;++o)for(unsigned i=0;i<3;++i)web_source::expected_tower_ids[o*3+i]=bootstrap_towers[o][i].id;
        web_source::elixir_checkpoint=bootstrap_page_end;
        web_source::Calls calls{b,p->services,source_readable,stable,p};
        if(bootstrap_run_loaded)web_source::run_loaded(calls,p->source,d,battle,bootstrap_events,bootstrap_source_end);
        else web_source::run(calls,p->source,d,battle,bootstrap_events,bootstrap_source_end);
        if(p->source.error==120){f[4]=45;return false;} // Retain until authorized process recovery.
    }
    // Release only our graph, only after complete native load/inspection.
    return release_loaded();
}
struct Task;using Method=void(*)(Task*)noexcept;struct Task{const Method* methods;Probe* p;};
void destroy(Task* t)noexcept{if(t->p)t->p->destroyed.store(1,std::memory_order_release);t->p=nullptr;}
void remove(Task* t)noexcept{destroy(t);delete t;}
void execute(Task* t)noexcept{
    auto* p=t->p;if(!p||p->entered.exchange(1))return;
    if(cr_noop_current_tid()!=p->tid||!stable(p)||!check_pins(p->base))p->fields[4]=20;
    else if(!location_cache_empty_ready(p)||!default_towers_ready(p)){
        // No native parser/Domain calls at all when its known input is absent.
        p->resource_preflight_rejected=true;p->fields[4]=30;
    } else {
        auto b=p->base;private_layout::Calls c{};
        c.allocate=&malloc;c.deallocate=reinterpret_cast<decltype(c.deallocate)>(b+0x1b34938);
        c.buffer_free=reinterpret_cast<decltype(c.buffer_free)>(b+0x1b34940);
        c.string_construct=reinterpret_cast<decltype(c.string_construct)>(b+0x16cb4d8);
        c.string_cleanup=reinterpret_cast<decltype(c.string_cleanup)>(b+0x16cb3c8);
        c.csv_construct=reinterpret_cast<decltype(c.csv_construct)>(b+0x152cd44);
        c.csv_cleanup=reinterpret_cast<decltype(c.csv_cleanup)>(b+0x152ceec);
        c.section=reinterpret_cast<decltype(c.section)>(b+0x152d824);
        c.table=reinterpret_cast<decltype(c.table)>(b+0x152d81c);
        c.cell=reinterpret_cast<decltype(c.cell)>(b+0x152dcdc);
        c.row_string=reinterpret_cast<decltype(c.row_string)>(b+0x152db84);
        c.row_value_count=reinterpret_cast<decltype(c.row_value_count)>(b+0x152db5c);
        c.layout_construct=reinterpret_cast<decltype(c.layout_construct)>(b+0x10da32c);
        c.layout_bind=reinterpret_cast<decltype(c.layout_bind)>(b+0x10da44c);
        c.layout_reset=reinterpret_cast<decltype(c.layout_reset)>(b+0x10da3b8);
        c.full_parse=reinterpret_cast<decltype(c.full_parse)>(b+0x10da758);
        c.readable=readable;c.services=p->services;c.lookup=lookup;c.stable=stable;c.context=p;
        private_layout::run(c,p->layout,asset_0,asset_0_size,asset_1,asset_1_size,expected_cells,
            map_width,map_height,expected_objects,expected_object_count,consume,p);
    }
    p->returned.store(1,std::memory_order_release);
}
const Method methods[]={destroy,remove,execute};
}
EXPORT int cr_web_bootstrap_start(uintptr_t b,int pid,uint64_t tid,uintptr_t handle,uintptr_t services){
    if(probe)return -1;
    if(!validated(b,pid,tid,handle)||!check_pins(b))return -2;
    auto root=read<uintptr_t>(b+0x1d34ae0);
    if(!readable(root,0x28)||read<uintptr_t>(root+0x20)!=services)return -3;
    auto* p=new(std::nothrow)Probe{b,services,root,tid};if(!p)return -4;
    auto* task=new(std::nothrow)Task{methods,p};if(!task){delete p;return -4;}
    probe=p;EmptyBinding binding{reinterpret_cast<unsigned char*>(b+0x1d88818)};
    bool accepted=publish_empty(&binding,reinterpret_cast<CrNoopTask*>(task));p->fields[0]=binding.result;
    if(!accepted)remove(task);return accepted;
}
EXPORT uintptr_t cr_web_bootstrap_done_address(){return probe?reinterpret_cast<uintptr_t>(&probe->destroyed):0;}
EXPORT uintptr_t cr_web_bootstrap_result_address(){
    if(!probe)return 0;probe->fields[1]=probe->entered;probe->fields[2]=probe->returned;probe->fields[3]=probe->destroyed;
    probe->fields[80]=probe->domain;probe->fields[81]=probe->json;
    probe->fields[82]=probe->layout.failure;probe->fields[83]=probe->layout.freed;
    probe->fields[84]=probe->layout.owned_layout;probe->fields[85]=probe->layout.owned_csv0;probe->fields[86]=probe->layout.owned_csv1;
    probe->fields[87]=probe->resource_preflight_rejected;
    probe->fields[88]=probe->cache_lease.stage;probe->fields[89]=probe->cache_lease.failure;
    probe->fields[90]=probe->cache_lease.layout;
    return reinterpret_cast<uintptr_t>(probe->fields);
}
EXPORT int cr_web_bootstrap_release(){
    if(!probe||!probe->destroyed)return 0;
    // A task the game queue refused never entered (entered==0): nothing was allocated.
    if(probe->domain||probe->json||(!probe->layout.freed&&!probe->resource_preflight_rejected&&probe->entered.load())||probe->layout.failure||probe->cache_lease.layout)return -1;
    delete probe;probe=nullptr;return 1;
}
EXPORT uintptr_t cr_web_source_text_address(){return probe&&probe->destroyed?reinterpret_cast<uintptr_t>(probe->source.text.c_str()):0;}
EXPORT uintptr_t cr_web_source_text_size(){return probe&&probe->destroyed?probe->source.text.size():0;}
EXPORT uintptr_t cr_web_bootstrap_towers_address(){return probe&&probe->destroyed?reinterpret_cast<uintptr_t>(probe->towers):0;}
