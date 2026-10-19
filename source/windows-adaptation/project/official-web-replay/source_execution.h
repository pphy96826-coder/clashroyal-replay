#pragma once
#include <string>
#include <chrono>
#include <vector>

namespace web_source {
struct Selection {uintptr_t first,second;uint32_t packed;};
struct Dispatch {uintptr_t command;int index,kind,code{-10000},tick{-1},flags{};};
struct Result {std::string text;int error{},event_index{},tick{},native_code{},executed{},finished{};
    int observed_hand[4]{},expected_card{},actual_side{-1},expected_slot{-1},available{},raw_elixir{},initial_elixir[2]{};
    std::vector<Dispatch> dispatch;};
struct Calls {uintptr_t base,services;bool(*readable)(uintptr_t,size_t);bool(*stable)(void*);void* context;};
template<class T> T field(uintptr_t p){T value{};std::memcpy(&value,reinterpret_cast<void*>(p),sizeof(value));return value;}
struct ReadRanges {
    struct Range {uintptr_t low,high;};std::vector<Range> ranges;
    bool refresh(){
        ranges.clear();FILE* stream=std::fopen("/proc/self/maps","r");if(!stream)return false;
        char line[1024];bool valid=true;
        while(std::fgets(line,sizeof(line),stream)){
            unsigned long long lo{},hi{};char mode[5]{};
            if(std::sscanf(line,"%llx-%llx %4s",&lo,&hi,mode)==3&&std::strchr(mode,'r'))ranges.push_back({lo,hi});
            if(ranges.size()>16384){valid=false;break;}
        }
        std::fclose(stream);return valid&&!ranges.empty();
    }
    bool contains(uintptr_t p,size_t n)const{
        p&=0x00ffffffffffffffULL;if(!p||!n||p+n<p)return false;
        auto covered=p;
        for(const auto& r:ranges){if(r.high<=covered)continue;if(r.low>covered)return false;covered=r.high;if(covered>=p+n)return true;}
        return false;
    }
};
inline ReadRanges* current_ranges{};
inline bool bounded_read(uintptr_t p,size_t n){return current_ranges&&current_ranges->contains(p,n);}
inline Result* active_trace{};
inline uintptr_t active_base{},deploy_table[34]{},ability_table[34]{};
inline int traced_execute(void* command,void* domain,int flags,int extra,int kind){
    // Observe ONLY our privately allocated command objects. Delegate unchanged
    // to the exact native implementation; no code patch, shared/global hook,
    // preflight reservation, validation bypass, or fake battle mutation.
    int tick=field<int>(reinterpret_cast<uintptr_t>(domain)+0x60);
    int code=reinterpret_cast<int(*)(void*,void*,int,int)>(active_base+(kind==153?0xf9ce58:0xf9fd0c))(command,domain,flags,extra);
    // Allocator addresses can be reused by later commands. Match the newest
    // still-pending generation, never overwrite an earlier command's result.
    if(active_trace)for(auto it=active_trace->dispatch.rbegin();it!=active_trace->dispatch.rend();++it)
        if(it->code==-10000&&(it->command&0x00ffffffffffffffULL)==(reinterpret_cast<uintptr_t>(command)&0x00ffffffffffffffULL)){
            it->code=code;it->tick=tick;it->flags=flags;break;
        }
    return code;
}
inline int traced_deploy(void* c,void* d,int flags,int extra){return traced_execute(c,d,flags,extra,153);}
inline int traced_ability(void* c,void* d,int flags,int extra){return traced_execute(c,d,flags,extra,189);}
inline bool trace_command(const Calls& c,Result& result,void* command,int kind){
    auto table=field<uintptr_t>(reinterpret_cast<uintptr_t>(command));
    if(!c.readable(table-16,34*8))return false;
    auto* copy=kind==153?deploy_table:ability_table;
    if(!copy[2]){
        std::memcpy(copy,reinterpret_cast<void*>(table-16),34*8);
        copy[5]=reinterpret_cast<uintptr_t>(kind==153?traced_deploy:traced_ability);
    }
    result.dispatch.push_back({reinterpret_cast<uintptr_t>(command),result.event_index,kind});
    uintptr_t owned_table=reinterpret_cast<uintptr_t>(copy+2);
    std::memcpy(command,&owned_table,8);return true;
}

// Copy the official command serializer's OWNED JSON body. No packed selection
// fields, native IDs, or JSON keys are invented by the source adapter.
inline bool native_text(const Calls& c,uintptr_t p,std::string& out){
    if(!c.readable(p,16))return false;
    int n=field<int>(p+4);if(n<0||n>48)return false;
    uintptr_t chars=n<8?p+8:field<uintptr_t>(p+8);
    if(!c.readable(chars,n+1)||field<char>(chars+n))return false;
    for(int i=0;i<n;++i){unsigned char ch=field<unsigned char>(chars+i);if(ch<32||ch>=127||ch=='"'||ch=='\\')return false;}
    out.assign(reinterpret_cast<char*>(chars),n);return true;
}
inline bool copy_json(const Calls& c,uintptr_t value,std::string& out,unsigned depth=0){
    if(depth>3||!c.readable(value,24))return false;
    auto table=field<uintptr_t>(value);
    if(table<c.base||table>=c.base+0x1d40000||!c.readable(table,0x18))return false;
    int kind=reinterpret_cast<int(*)(void*)>(field<uintptr_t>(table+0x10))(reinterpret_cast<void*>(value));
    if(kind==3){
        if(field<unsigned char>(value+8))return false; // Reject float representation.
        out+=std::to_string(field<int64_t>(value+0x10));return true;
    }
    if(kind!=2||!c.readable(value,0x50))return false;
    int count=field<int>(value+0x4c),capacity=field<int>(value+0x48);
    if(count<0||count>16||count>capacity)return false;
    auto names=field<uintptr_t>(value+0x40);
    if(count&&!c.readable(names,count*16))return false;
    out+='{';
    for(int i=0;i<count;++i){
        auto name=names+i*16;std::string key;if(!native_text(c,name,key))return false;
        auto node=reinterpret_cast<uintptr_t(*)(void*,void*)>(c.base+0x89d3e0)(reinterpret_cast<void*>(value+0x18),reinterpret_cast<void*>(name));
        if(!c.readable(node,0x28))return false;
        if(i)out+=',';out+='"';out+=key;out+="\":";
        if(!copy_json(c,field<uintptr_t>(node+0x20),out,depth+1))return false;
    }
    out+='}';return true;
}
inline void delete_command(const Calls& c,void* command){
    (void)c;auto table=field<uintptr_t>(reinterpret_cast<uintptr_t>(command));
    reinterpret_cast<void(*)(void*)>(field<uintptr_t>(table))(command);
    reinterpret_cast<void(*)(void*)>(field<uintptr_t>(table+0x10))(command);
}

// Round-trip test: commands come ONLY from the official JSON loader. No
// enqueue, card selection, retiming or source injection is performed here.
template<class Events>
inline void run_loaded(const Calls& original,Result& result,uintptr_t d,uintptr_t battle,const Events& events,int end){
    Calls c=original;ReadRanges memory;current_ranges=&memory;c.readable=bounded_read;
    const auto b=c.base;active_trace=&result;active_base=b;
    std::string commands="[",dispatch="[";
    auto queue=field<uintptr_t>(d+0x38);
    if(!memory.refresh()||!c.readable(queue,0x28)||field<int>(queue+0x14)!=int(sizeof(events)/sizeof(events[0])))result.error=201;
    unsigned index=0;
    if(!result.error)for(const auto& event:events){
        auto entries=field<uintptr_t>(queue+8);
        if(!c.readable(entries,(index+1)*8)){result.error=202;break;}
        auto command=field<uintptr_t>(entries+index*8);
        if(!c.readable(command,event.kind==153?88:56)||field<uintptr_t>(command)!=b+(event.kind==153?0x1bf6260:0x1bf69b0)||
           field<int>(command+0xc)!=event.tick||field<int>(command+0x10)!=event.tick){result.error=203;break;}
        // Native type getter and serializer independently confirm decoded JSON.
        auto table=field<uintptr_t>(command);
        if(reinterpret_cast<int(*)(void*)>(field<uintptr_t>(table+0x20))(reinterpret_cast<void*>(command))!=event.kind){result.error=204;break;}
        auto body=reinterpret_cast<void*(*)(void*)>(b+(event.kind==153?0xf9d370:0xf9ff78))(reinterpret_cast<void*>(command));
        std::string text;bool copied=body&&memory.refresh()&&copy_json(c,reinterpret_cast<uintptr_t>(body),text);
        if(body){auto v=field<uintptr_t>(reinterpret_cast<uintptr_t>(body));reinterpret_cast<void(*)(void*)>(field<uintptr_t>(v+8))(body);}
        if(!copied){result.error=205;break;}
        result.event_index=index;
        if(!trace_command(c,result,reinterpret_cast<void*>(command),event.kind)){result.error=206;break;}
        if(index)commands+=',';commands+="{\"ct\":"+std::to_string(event.kind)+",\"c\":"+text+'}';++index;
    }
    auto started=std::chrono::steady_clock::now();
    auto done=[&](){return reinterpret_cast<int(*)(void*)>(b+0xf5603c)(reinterpret_cast<void*>(battle));};
    while(!result.error&&field<int>(d+0x60)<end&&!done()){
        int before=field<int>(d+0x60);
        reinterpret_cast<int(*)(void*)>(b+0x1366f64)(reinterpret_cast<void*>(d));
        if(field<int>(d+0x60)!=before+1){result.error=207;break;}
        if(before%200==199&&(!c.stable(c.context)||std::chrono::steady_clock::now()-started>std::chrono::seconds(20))){result.error=208;break;}
    }
    unsigned accepted=0;int failed=-1;
    for(const auto& entry:result.dispatch){
        if(dispatch.size()>1)dispatch+=',';
        dispatch+="{\"index\":"+std::to_string(entry.index)+",\"kind\":"+std::to_string(entry.kind)+",\"tick\":"+std::to_string(entry.tick)+",\"flags\":"+std::to_string(entry.flags)+",\"code\":"+std::to_string(entry.code)+'}';
        if(entry.code==0)++accepted;else if(failed<0)failed=entry.index;
    }
    result.tick=field<int>(d+0x60);result.finished=done();result.executed=index;result.event_index=index;
    if(!result.error&&(accepted!=index||!result.finished))result.error=209;
    commands+=']';dispatch+=']';active_trace=nullptr;current_ranges=nullptr;
    result.text="{\"error\":"+std::to_string(result.error)+",\"event_index\":"+std::to_string(index)+",\"tick\":"+std::to_string(result.tick)+",\"native_code\":0,\"executed\":"+std::to_string(index)+",\"native_accepted\":"+std::to_string(accepted)+",\"failed_index\":"+std::to_string(failed)+",\"finished\":"+std::to_string(result.finished)+",\"loaded_from_json\":true,\"commands\":"+commands+",\"diagnostics\":[],\"dispatch\":"+dispatch+'}';
}

template<class Events>
inline void run(const Calls& original,Result& result,uintptr_t d,uintptr_t battle,const Events& events,int end){
    Calls c=original;ReadRanges memory;current_ranges=&memory;c.readable=bounded_read;
    const auto b=c.base;std::string commands="[",diagnostics="[";bool first=true;
    active_trace=&result;active_base=b;
    auto step=reinterpret_cast<int(*)(void*)>(b+0x1366f64);
    auto done=[&](){return reinterpret_cast<int(*)(void*)>(b+0xf5603c)(reinterpret_cast<void*>(battle));};
    auto started=std::chrono::steady_clock::now();
    for(unsigned side=0;side<2;++side){
        auto root=field<uintptr_t>(battle+0xe0+side*8);
        result.initial_elixir[side]=reinterpret_cast<int(*)(void*,int)>(b+0x120c810)(reinterpret_cast<void*>(root),1);
    }
    auto advance=[&](int target,bool allow_terminal=false){
        while(field<int>(d+0x60)<target){
            int before=field<int>(d+0x60);
            if(done()){if(allow_terminal)return true;result.error=101;return false;}
            step(reinterpret_cast<void*>(d));
            if(field<int>(d+0x60)!=before+1){result.error=102;return false;}
            for(const auto& entry:result.dispatch)if(entry.code>0){result.error=114;result.native_code=entry.code;return false;}
            if(before%200==199&&(!c.stable(c.context)||std::chrono::steady_clock::now()-started>std::chrono::seconds(20))){result.error=103;return false;}
        }
        return field<int>(d+0x60)==target;
    };
    for(const auto& event:events){
        result.tick=event.tick;
        result.expected_card=event.id;result.actual_side=event.owner;result.expected_slot=event.cycle_slot;
        if(event.owner<0||event.owner>1||!advance(event.tick)){if(!result.error)result.error=104;break;}
        // Snapshot AFTER native stepping, and again after native serialization
        // has finished allocating its complete JSON tree. Hundreds of repeated
        // /proc reads per command are unnecessary; no owner is freed while read.
        if(!memory.refresh()){result.error=118;break;}
        auto root=field<uintptr_t>(battle+0xe0+event.owner*8);
        if(!c.readable(root,0x418)){result.error=105;break;}
        result.available=reinterpret_cast<int(*)(void*,int)>(b+0x120c810)(reinterpret_cast<void*>(root),1);
        result.raw_elixir=field<int>(root+0x300);
        void* command=nullptr;int slot=-1;unsigned packed=0;
        if(event.kind==153){
            // Source HTML identifies the card, not a private slot. The plain
            // cycle model's slot is only an inference; always resolve the
            // EXACT source card from actual native hand (no substitute card).
            void* card=nullptr;unsigned matches=0;
            for(int i=0;i<4;++i){
                result.observed_hand[i]=0;
                auto candidate=reinterpret_cast<void*(*)(void*,int)>(b+0x12085b4)(reinterpret_cast<void*>(root),i);
                if(!candidate)continue;
                if(!c.readable(reinterpret_cast<uintptr_t>(candidate),0x50)){result.error=106;break;}
                auto definition=field<uintptr_t>(reinterpret_cast<uintptr_t>(candidate)+0x10);
                if(!c.readable(definition,0x44)){result.error=106;break;}
                result.observed_hand[i]=field<int>(definition+0x40);
                if(result.observed_hand[i]==event.id){card=candidate;slot=i;++matches;}
            }
            if(result.error)break;
            if(matches!=1){result.error=107;result.native_code=matches;break;}
            auto selected=reinterpret_cast<Selection(*)(void*,void*,int)>(b+0x10cebe0)(card,reinterpret_cast<void*>(root),1);
            auto actual=reinterpret_cast<uintptr_t>(reinterpret_cast<void*(*)(void*)>(b+0x10ce6a4)(&selected));
            if(!c.readable(actual,0x44)){result.error=108;break;}
            packed=selected.packed;
            command=malloc(88);if(!command){result.error=109;break;}
            reinterpret_cast<void(*)(void*,void*)>(b+0xf9ce00)(command,reinterpret_cast<void*>(c.services));
            reinterpret_cast<void(*)(void*,void*)>(b+0xf9d5e0)(command,&selected);
            reinterpret_cast<void(*)(void*,int,int)>(b+0xf9d368)(command,event.x,event.y);
        }else if(event.kind==189){
            auto manager=field<uintptr_t>(d+0x40);if(!c.readable(manager,0x18)){result.error=110;break;}
            int count=field<int>(manager+0x14);auto objects=field<uintptr_t>(manager+8);
            if(count<0||count>1024||!c.readable(objects,count*8)){result.error=111;break;}
            uintptr_t actor=0;unsigned eligible=0;
            for(int i=0;i<count;++i){
                auto object=field<uintptr_t>(objects+i*8);
                if(!c.readable(object,0x88)||field<int>(object+0x78)!=event.owner)continue;
                auto definition=field<uintptr_t>(object+0x48);
                if(!c.readable(definition,0x728)||!field<uintptr_t>(definition+0x720))continue;
                auto table=field<uintptr_t>(object);if(!c.readable(table,0x198))continue;
                if(!reinterpret_cast<int(*)(void*)>(field<uintptr_t>(table+0x190))(reinterpret_cast<void*>(object)))continue;
                if(reinterpret_cast<int(*)(void*,void*,void*)>(b+0x120f614)(reinterpret_cast<void*>(root),reinterpret_cast<void*>(d),reinterpret_cast<void*>(object)))continue;
                actor=object;++eligible;
            }
            if(eligible!=1){result.error=112;result.native_code=eligible;break;}
            command=malloc(56);if(!command){result.error=109;break;}
            reinterpret_cast<void(*)(void*,void*,void*)>(b+0xf9fcac)(command,reinterpret_cast<void*>(c.services),reinterpret_cast<void*>(actor));
        }else{result.error=113;break;}
        reinterpret_cast<void(*)(void*,int)>(b+0xf96dcc)(command,event.tick);
        // Replay queue compares C+0xc (serialized t2), NOT C+0x10 (t).
        // Leaving ctor's t2=-1 makes every source command stale and discarded.
        reinterpret_cast<void(*)(void*,int)>(b+0xf96cf4)(command,event.tick);
        reinterpret_cast<void(*)(void*,void*)>(b+0xf96de8)(command,reinterpret_cast<void*>(field<uintptr_t>(battle+0x30+event.owner*8)));
        // A replay command is NOT a user-click request. Calling flags1 here
        // reserves elixir/intents unnecessarily; the replay queue dispatches
        // flags3 and performs all real native validation and execution itself.
        auto body=reinterpret_cast<void*(*)(void*)>(b+(event.kind==153?0xf9d370:0xf9ff78))(command);
        auto bodyptr=reinterpret_cast<uintptr_t>(body);std::string text;
        bool copied=body&&memory.refresh()&&copy_json(c,bodyptr,text);
        if(body){auto table=field<uintptr_t>(bodyptr);reinterpret_cast<void(*)(void*)>(field<uintptr_t>(table+8))(body);}
        if(!copied){result.error=115;delete_command(c,command);break;}
        if(!trace_command(c,result,command,event.kind)){result.error=116;delete_command(c,command);break;}
        if(!first){commands+=',';diagnostics+=',';}first=false;
        commands+="{\"ct\":"+std::to_string(event.kind)+",\"c\":"+text+'}';
        diagnostics+="{\"index\":"+std::to_string(result.event_index)+",\"tick\":"+std::to_string(event.tick)+",\"owner\":"+std::to_string(event.owner)+",\"card\":"+std::to_string(event.id)+",\"slot\":"+std::to_string(slot)+",\"available\":"+std::to_string(result.available)+",\"raw_elixir\":"+std::to_string(result.raw_elixir)+",\"packed\":"+std::to_string(packed)+'}';
        // Queue now owns the native command; normal step executes it. The
        // native append retains the caller's pointer: do not delete it here.
        reinterpret_cast<void(*)(void*,void**)>(b+0xf9ab04)(reinterpret_cast<void*>(field<uintptr_t>(d+0x38)),&command);
        ++result.executed;++result.event_index;
    }
    if(!result.error)advance(end,true);
    result.tick=field<int>(d+0x60);result.finished=done();
    active_trace=nullptr;
    current_ranges=nullptr;
    commands+=']';diagnostics+=']';
    std::string dispatch="[";unsigned accepted=0;int failed_index=-1;
    for(const auto& entry:result.dispatch){
        if(dispatch.size()>1)dispatch+=',';
        dispatch+="{\"index\":"+std::to_string(entry.index)+",\"kind\":"+std::to_string(entry.kind)+",\"tick\":"+std::to_string(entry.tick)+",\"flags\":"+std::to_string(entry.flags)+",\"code\":"+std::to_string(entry.code)+'}';
        if(entry.code==0)++accepted;else if(failed_index<0)failed_index=entry.index;
    }
    dispatch+=']';
    std::string hand="[";for(unsigned i=0;i<4;++i){if(i)hand+=',';hand+=std::to_string(result.observed_hand[i]);}hand+=']';
    result.text="{\"error\":"+std::to_string(result.error)+",\"event_index\":"+std::to_string(result.event_index)+",\"tick\":"+std::to_string(result.tick)+",\"native_code\":"+std::to_string(result.native_code)+",\"executed\":"+std::to_string(result.executed)+",\"native_accepted\":"+std::to_string(accepted)+",\"failed_index\":"+std::to_string(failed_index)+",\"finished\":"+std::to_string(result.finished)+",\"expected_card\":"+std::to_string(result.expected_card)+",\"owner\":"+std::to_string(result.actual_side)+",\"available\":"+std::to_string(result.available)+",\"raw_elixir\":"+std::to_string(result.raw_elixir)+",\"initial_elixir\":["+std::to_string(result.initial_elixir[0])+','+std::to_string(result.initial_elixir[1])+"],\"last_hand\":"+hand+",\"commands\":"+commands+",\"diagnostics\":"+diagnostics+",\"dispatch\":"+dispatch+'}';
}
}
