#pragma once
#include <cstdint>
#include <cstring>
#include <cstddef>
#include <initializer_list>

// A scope-bound lease over ONE initially empty, already allocated Location
// cache slot. Never grows the vector or replaces an existing Layout. The
// canonical native factory creates the cached Layout from owned local CSVs;
// those CSVs MUST outlive the lease. No file/network resource loader is used.
namespace replay_cache {
constexpr uintptr_t mask=0x00ffffffffffffffULL;
template<class T>T at(uintptr_t p,size_t o){T v{};std::memcpy(&v,reinterpret_cast<void*>(p+o),sizeof(v));return v;}
struct Calls {
    bool(*readable)(uintptr_t,size_t);
    bool(*stable)(void*);void* context;
    void(*create)(void*,void*,void*,int);
    void(*reset)(void*);void(*buffer_free)(void*);void(*string_cleanup)(void*);void(*object_free)(void*);
};
struct Lease {
    uintptr_t services{},csv[2]{},layout{},cache{},snapshot[512]{};
    unsigned char header[16]{};
    int index{61},count{};unsigned stage{},failure{};
};
inline bool same(uintptr_t a,uintptr_t b){return (a&mask)==(b&mask);}
inline bool topology(const Calls& c,const Lease& l,bool own_slot){
    if(!c.stable(l.services?c.context:nullptr)||!c.readable(l.services+0x13d8,16)||
       std::memcmp(reinterpret_cast<void*>(l.services+0x13d8),l.header,16)||
       !c.readable(l.cache,size_t(l.count)*8))return false;
    for(int i=0;i<l.count;++i){
        auto value=at<uintptr_t>(l.cache,size_t(i)*8);
        if(i==l.index){if(value!=(own_slot?l.layout:0))return false;}
        else if(value!=l.snapshot[i])return false;
    }
    return true;
}
inline bool acquire(const Calls& c,Lease& l,uintptr_t services,void* csv0,void* csv1,unsigned w,unsigned h){
    if(l.stage||l.failure||!c.readable||!c.stable||!c.create||!c.reset||!c.buffer_free||!c.string_cleanup||!c.object_free)return false;
    l.services=services;l.csv[0]=reinterpret_cast<uintptr_t>(csv0);l.csv[1]=reinterpret_cast<uintptr_t>(csv1);
    if(!c.stable(c.context)||!c.readable(services+0x13d8,16)){l.failure=1;return false;}
    std::memcpy(l.header,reinterpret_cast<void*>(services+0x13d8),16);
    l.cache=at<uintptr_t>(services,0x13d8);int capacity=at<int>(services,0x13e0);l.count=at<int>(services,0x13e4);
    if(l.count<=l.index||l.count>capacity||capacity>512||!c.readable(l.cache,size_t(l.count)*8)){l.failure=2;return false;}
    std::memcpy(l.snapshot,reinterpret_cast<void*>(l.cache),size_t(l.count)*8);
    if(l.snapshot[l.index]){l.failure=3;return false;} // never replace borrowed cache
    if(!topology(c,l,false)){l.failure=4;return false;}
    l.stage=1;c.create(reinterpret_cast<void*>(services),csv0,csv1,l.index);
    l.layout=at<uintptr_t>(l.cache,size_t(l.index)*8);l.stage=2;
    if(!l.layout||!topology(c,l,true)||!c.readable(l.layout,0xb0)||
       !same(at<uintptr_t>(l.layout,0),services)||at<uintptr_t>(l.layout,0x68)!=l.csv[0]||
       at<uintptr_t>(l.layout,0x80)!=l.csv[1]||at<unsigned>(l.layout,0xa8)!=w||at<unsigned>(l.layout,0xac)!=h){l.failure=5;return false;}
    l.stage=3;return true;
}
inline bool release(const Calls& c,Lease& l,bool replay_graph_released){
    if(l.stage!=3||l.failure||!replay_graph_released||!topology(c,l,true)){return false;}
    uintptr_t vectors[4]{};unsigned i=0;
    for(size_t off:{size_t(0x58),size_t(0x48),size_t(0x38),size_t(0x28)}){
        auto data=at<uintptr_t>(l.layout,off);int capacity=at<int>(l.layout,off+8),count=at<int>(l.layout,off+12);
        if(count<0||count>capacity||capacity>128||(capacity&&!c.readable(data,size_t(capacity)*8)))return false;
        vectors[i++]=data;
    }
    // All client work is on the same serialized native worker. Remove only the
    // entry we created, before freeing it; reject concurrent/foreign changes.
    uintptr_t zero=0;std::memcpy(reinterpret_cast<void*>(l.cache+size_t(l.index)*8),&zero,8);l.stage=4;
    c.reset(reinterpret_cast<void*>(l.layout));
    if(at<uintptr_t>(l.layout,0x98)||at<uintptr_t>(l.layout,0xa0)||at<uintptr_t>(l.layout,0x68)||at<uintptr_t>(l.layout,0x80)){
        l.failure=6;return false;
    }
    i=0;
    for(size_t off:{size_t(0x58),size_t(0x48),size_t(0x38),size_t(0x28)}){
        if(at<uintptr_t>(l.layout,off)!=vectors[i++]){l.failure=7;return false;}
        if(auto value=at<uintptr_t>(l.layout,off))c.buffer_free(reinterpret_cast<void*>(value));
        std::memset(reinterpret_cast<void*>(l.layout+off),0,16);
    }
    c.string_cleanup(reinterpret_cast<void*>(l.layout+0x18));c.string_cleanup(reinterpret_cast<void*>(l.layout+8));
    c.object_free(reinterpret_cast<void*>(l.layout));l.layout=0;
    if(!topology(c,l,false)){l.failure=8;return false;}
    l.stage=5;return true;
}
}
