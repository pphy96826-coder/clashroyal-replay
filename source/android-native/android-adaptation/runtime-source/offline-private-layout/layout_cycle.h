#pragma once
#include "../offline-private-map/map_cycle.h"
#include <cstdio>

namespace private_layout {
using private_map::field;
struct ExpectedObject { const char* name; int x, y; };
struct Result : private_map::Result {
    std::atomic<unsigned> expected_objects{0}, actual_objects{0}, actual_background{0},
        vectors_allocated{0}, vectors_freed{0}, preflight_completed{0}, failure{0},
        full_parser_calls{0}, aborted_cleanly{0};
    std::atomic<uintptr_t> owned_csv0{0}, owned_csv1{0}, owned_layout{0};
};
struct Calls : private_map::Calls {
    void (*buffer_free)(void*);
    void (*full_parse)(void*,void*);
    void* (*row_string)(void*,const char*,int);
    int (*row_value_count)(void*,int);
    void* (*lookup)(unsigned,void*);
    bool (*stable)(void*);
    void* context;
};
struct RetainedRow { uintptr_t row, type; int x,y; };

inline bool text_equals(const Calls& c,void* native,const char* expected) {
    if(!native || !c.readable(reinterpret_cast<uintptr_t>(native),16))return false;
    const auto length=field<int>(native,4);
    if(length<0 || length>96 || size_t(length)!=std::strlen(expected))return false;
    auto* data=length<8?static_cast<unsigned char*>(native)+8:
        reinterpret_cast<unsigned char*>(field<uintptr_t>(native,8));
    return c.readable(reinterpret_cast<uintptr_t>(data),size_t(length)) &&
        !std::memcmp(data,expected,size_t(length));
}
inline bool vector_safe(const Calls& c,void* layout,size_t offset) {
    const auto p=field<uintptr_t>(layout,offset);
    const int capacity=field<int>(layout,offset+8),count=field<int>(layout,offset+12);
    return count>=0 && capacity>=count && capacity<=128 &&
        (!capacity?(!p&&!count):(p && c.readable(p,size_t(capacity)*8)));
}
inline bool allocations_distinct(void* layout,void* csv0,void* csv1) {
    uintptr_t values[]={field<uintptr_t>(layout,0x28),field<uintptr_t>(layout,0x38),
        field<uintptr_t>(layout,0x48),field<uintptr_t>(layout,0x58),
        field<uintptr_t>(layout,0x98),field<uintptr_t>(layout,0xa0),
        reinterpret_cast<uintptr_t>(layout),reinterpret_cast<uintptr_t>(csv0),reinterpret_cast<uintptr_t>(csv1)};
    for(unsigned i=0;i<9;++i)for(unsigned j=i+1;j<9;++j)
        if(values[i]&&values[i]==values[j])return false;
    return true;
}

// Fixed private fixture. Optional consumer must finish its borrowed Layout use
// before returning true; false/exception retains Layout/CSVs, never guesses cleanup.
inline void run(const Calls& c,Result& r,const char* first,int first_size,
    const char* second,int second_size,const int* cells,unsigned width,unsigned height,
    const ExpectedObject* objects,unsigned object_count,
    bool (*consumer)(void*,void*)=nullptr,void* consumer_context=nullptr) noexcept {
    void* csv[2]{};void* layout{};
    alignas(16) unsigned char names[6][16]{};
    unsigned name_count=0,csv_count=0;bool layout_ready=false,parser_started=false;
    RetainedRow expected[32]{};unsigned expected_count=0;
    auto audit=[&](private_map::AuditPoint p) noexcept {if(c.audit)c.audit(c.audit_context,p);};
    auto fail=[&](unsigned code) {r.failure.store(code);r.stage.store(private_map::INVARIANT_FAILED);};
    // Only called for completely constructed objects, or known unconstructed
    // outer allocations. Any exception/unsafe container retains exact owners.
    auto cleanup=[&](bool abort) {
        if(layout_ready) {
            if(!allocations_distinct(layout,csv[0],csv[1])){fail(93);return false;}
            for(size_t offset:{size_t(0x28),size_t(0x38),size_t(0x48),size_t(0x58)})
                if(!vector_safe(c,layout,offset)) {fail(90);return false;}
            uintptr_t buffers[4]{};unsigned index=0;
            for(size_t offset:{size_t(0x58),size_t(0x48),size_t(0x38),size_t(0x28)})
                buffers[index++]=field<uintptr_t>(layout,offset);
            r.stage.store(private_map::CLEANING);
            c.layout_reset(layout);r.layout_cleaned.store(1);
            if(field<uintptr_t>(layout,0x98)||field<uintptr_t>(layout,0xa0)||
               field<uintptr_t>(layout,0x68)||field<uintptr_t>(layout,0x80)) {fail(91);return false;}
            index=0;
            for(size_t offset:{size_t(0x58),size_t(0x48),size_t(0x38),size_t(0x28)}) {
                if(field<uintptr_t>(layout,offset)!=buffers[index++]) {fail(92);return false;}
                if(auto p=field<uintptr_t>(layout,offset)) {
                    c.buffer_free(reinterpret_cast<void*>(p));r.vectors_freed.fetch_add(1);
                }
                std::memset(static_cast<unsigned char*>(layout)+offset,0,16);
            }
            if(!abort)audit(private_map::LAYOUT_RESET);
            c.string_cleanup(static_cast<unsigned char*>(layout)+0x18);
            c.string_cleanup(static_cast<unsigned char*>(layout)+8);
            if(!abort)audit(private_map::LAYOUT_STRINGS_CLEAN);
        }
        c.deallocate(layout);layout=nullptr;r.owned_layout.store(0);r.retained.fetch_sub(1);
        if(!abort)audit(private_map::LAYOUT_FREED);
        for(unsigned i=0;i<2;++i) {
            if(i<csv_count){c.csv_cleanup(csv[i]);r.csv_cleaned.fetch_add(1);}
            if(!abort)audit(i==0?private_map::CSV0_CLEAN:private_map::CSV1_CLEAN);
            c.deallocate(csv[i]);csv[i]=nullptr;r.retained.fetch_sub(1);
            (i==0?r.owned_csv0:r.owned_csv1).store(0);
            if(!abort)audit(i==0?private_map::CSV0_FREED:private_map::CSV1_FREED);
        }
        while(name_count)c.string_cleanup(names[--name_count]);
        if(!abort)audit(private_map::NAMES_CLEAN);
        r.freed.store(1);
        if(abort){r.aborted_cleanly.store(1);r.stage.store(private_map::REJECTED);}
        else {r.stage.store(private_map::FREED);audit(private_map::FINISHED);}
        return true;
    };
    try {
        if(!first||!second||!cells||!objects||first_size<=0||second_size<=0||
            !width||!height||width>128||height>128||!object_count||object_count>32) {
            r.stage.store(private_map::REJECTED);return;
        }
        audit(private_map::BEGIN);
        csv[0]=c.allocate(0x68);csv[1]=c.allocate(0x68);layout=c.allocate(0xb0);
        if(!csv[0]||!csv[1]||!layout) {
            for(auto p:csv)if(p)c.deallocate(p);
            if(layout)c.deallocate(layout);
            r.failure.store(1);r.stage.store(private_map::REJECTED);return;
        }
        r.owned_csv0.store(reinterpret_cast<uintptr_t>(csv[0]));
        r.owned_csv1.store(reinterpret_cast<uintptr_t>(csv[1]));
        r.owned_layout.store(reinterpret_cast<uintptr_t>(layout));
        r.retained.store(3);r.stage.store(private_map::ALLOCATED);
        std::memset(csv[0],0,0x68);std::memset(csv[1],0,0x68);std::memset(layout,0,0xb0);
        audit(private_map::OUTER_ALLOCATED);
        const char* labels[]={"locations/dragon_arena.csv","tilemaps/tilemap.csv","Map",
                              "FileName","Objects","Background"};
        for(auto label:labels){c.string_construct(names[name_count],label);++name_count;}
        audit(private_map::NAMES_READY);r.stage.store(private_map::PARSING);
        for(unsigned i=0;i<2;++i) {
            c.csv_construct(csv[i],i?second:first,i?second_size:first_size,names[i]);
            ++csv_count;r.csv_constructed.fetch_add(1);
            audit(i==0?private_map::CSV0_READY:private_map::CSV1_READY);
        }
        r.stage.store(private_map::PARSED);
        auto section=c.section(csv[0],names[3]);
        auto table=section&&c.readable(reinterpret_cast<uintptr_t>(section),0x68)?c.table(section):nullptr;
        if(!table||!c.readable(reinterpret_cast<uintptr_t>(table),0x64)||field<int>(table,0x54)!=1||
            !c.readable(field<uintptr_t>(table,0x48),8)) {fail(10);cleanup(true);return;}
        auto row=reinterpret_cast<void*>(field<uintptr_t>(reinterpret_cast<void*>(field<uintptr_t>(table,0x48)),0));
        if(!row||!c.readable(reinterpret_cast<uintptr_t>(row),16)||
           !text_equals(c,c.row_string(row,"SC",0),"sc/level_dragon_arena_dl.sc")||
           !text_equals(c,c.row_string(row,"ExportName",0),"dragon_base_01")) {fail(11);cleanup(true);return;}
        section=c.section(csv[1],names[2]);
        table=section&&c.readable(reinterpret_cast<uintptr_t>(section),0x68)?c.table(section):nullptr;
        if(!table||!c.readable(reinterpret_cast<uintptr_t>(table),0x64)||field<unsigned>(table,0x34)!=width||
           field<unsigned>(table,0x54)!=height||!c.readable(field<uintptr_t>(table,0x48),height*8)) {
            fail(12);cleanup(true);return;
        }
        for(unsigned y=0;y<height;++y) {
            row=reinterpret_cast<void*>(field<uintptr_t>(reinterpret_cast<void*>(field<uintptr_t>(table,0x48)),y*8));
            if(!row||!c.readable(reinterpret_cast<uintptr_t>(row),16)||
               field<uintptr_t>(row,0)!=reinterpret_cast<uintptr_t>(table)||field<unsigned>(row,8)!=y) {
                fail(13);cleanup(true);return;
            }
            for(unsigned x=0;x<width;++x)if(c.cell(row,int(x))!=cells[y*width+x])r.csv_mismatches.fetch_add(1);
        }
        if(r.csv_mismatches.load()){fail(14);cleanup(true);return;}
        // This fixed fixture has no background child tables; validate rather
        // than silently skipping potentially unsafe/unseen background types.
        auto background=c.section(csv[0],names[5]);
        if(!background||!c.readable(reinterpret_cast<uintptr_t>(background),0x68)||field<int>(background,0x14)!=0) {
            fail(15);cleanup(true);return;
        }
        auto object_section=c.section(csv[0],names[4]);
        if(!object_section||!c.readable(reinterpret_cast<uintptr_t>(object_section),0x68)) {
            fail(16);cleanup(true);return;
        }
        const int child_count=field<int>(object_section,0x14);
        auto children=field<uintptr_t>(object_section,8);
        if(child_count<1||child_count>32||!c.readable(children,size_t(child_count)*8)) {fail(17);cleanup(true);return;}
        unsigned observed_rows=0;bool matched[32]{};
        for(int i=0;i<child_count;++i) {
            auto child=reinterpret_cast<void*>(field<uintptr_t>(reinterpret_cast<void*>(children),size_t(i)*8));
            if(!child||!c.readable(reinterpret_cast<uintptr_t>(child),0x68)){fail(18);cleanup(true);return;}
            auto child_table=c.table(child);
            if(!child_table)continue;
            if(!c.readable(reinterpret_cast<uintptr_t>(child_table),0x64)){fail(19);cleanup(true);return;}
            const int count=field<int>(child_table,0x54);
            if(!count)continue;
            if(count<0||count>32||field<int>(child_table,0x34)!=2||
               !c.readable(field<uintptr_t>(child_table,0x48),size_t(count)*8)) {fail(20);cleanup(true);return;}
            if(!c.stable(c.context)){fail(21);cleanup(true);return;}
            auto type=c.lookup(97,static_cast<unsigned char*>(child)+0x20);
            if(!type)type=c.lookup(6,static_cast<unsigned char*>(child)+0x20);
            if(!c.stable(c.context)){fail(21);cleanup(true);return;}
            for(int j=0;j<count;++j) {
                row=reinterpret_cast<void*>(field<uintptr_t>(reinterpret_cast<void*>(field<uintptr_t>(child_table,0x48)),size_t(j)*8));
                if(!row||!c.readable(reinterpret_cast<uintptr_t>(row),16)||
                   field<uintptr_t>(row,0)!=reinterpret_cast<uintptr_t>(child_table)||field<unsigned>(row,8)!=unsigned(j)) {
                    fail(22);cleanup(true);return;
                }
                const int x=c.cell(row,0),y=c.cell(row,1);
                int match=-1;
                for(unsigned k=0;k<object_count;++k)if(!matched[k]&&objects[k].x==x&&objects[k].y==y&&
                    text_equals(c,static_cast<unsigned char*>(child)+0x20,objects[k].name)) {match=int(k);break;}
                if(match<0){fail(23);cleanup(true);return;}
                matched[match]=true;++observed_rows;
                // Native API counts the row's present values, not numeric x.
                if(type&&c.row_value_count(row,0)>0) {
                    if(expected_count==32){fail(24);cleanup(true);return;}
                    expected[expected_count++]={reinterpret_cast<uintptr_t>(row),reinterpret_cast<uintptr_t>(type),x,y};
                }
            }
        }
        if(observed_rows!=object_count){fail(25);cleanup(true);return;}
        r.expected_objects.store(expected_count);r.preflight_completed.store(1);
        audit(private_map::CSV_CHECKED);
        c.layout_construct(layout,reinterpret_cast<void*>(c.services));layout_ready=true;r.layout_constructed.store(1);
        audit(private_map::LAYOUT_READY);c.layout_bind(layout,csv[0],csv[1]);audit(private_map::LAYOUT_BOUND);
        if(!c.stable(c.context)){fail(21);cleanup(true);return;}
        parser_started=true;r.full_parser_calls.store(1);
        c.full_parse(layout,reinterpret_cast<void*>(c.services));r.stage.store(private_map::MAP_PARSED);
        audit(private_map::GEOMETRY_READY);
        bool stable=c.stable(c.context);bool safe=true;
        for(size_t offset:{size_t(0x28),size_t(0x38),size_t(0x48),size_t(0x58)}) {
            safe=safe&&vector_safe(c,layout,offset);
            if(field<uintptr_t>(layout,offset))r.vectors_allocated.fetch_add(1);
        }
        if(!safe){fail(90);return;}
        r.actual_objects.store(field<unsigned>(layout,0x34));r.actual_background.store(field<unsigned>(layout,0x54));
        if(!stable){fail(26);cleanup(true);return;}
        if(r.actual_objects.load()!=expected_count||field<unsigned>(layout,0x44)!=expected_count||
            r.actual_background.load()||field<unsigned>(layout,0x64)) {fail(27);cleanup(true);return;}
        auto object_rows=field<uintptr_t>(layout,0x28),types=field<uintptr_t>(layout,0x38);
        for(unsigned i=0;i<expected_count;++i)if(
            field<uintptr_t>(reinterpret_cast<void*>(object_rows),i*8)!=expected[i].row||
            field<uintptr_t>(reinterpret_cast<void*>(types),i*8)!=expected[i].type) {fail(28);cleanup(true);return;}
        r.width.store(field<unsigned>(layout,0xa8));r.height.store(field<unsigned>(layout,0xac));
        auto low=field<uintptr_t>(layout,0x98),high=field<uintptr_t>(layout,0xa0);
        if(r.width.load()!=width||r.height.load()!=height||!c.readable(low,width*height*4)||
            !c.readable(high,width*height*4)) {fail(29);cleanup(true);return;}
        for(unsigned i=0;i<width*height;++i)if(field<int>(reinterpret_cast<void*>(low),i*4)!=(cells[i]&0x7f)||
            field<int>(reinterpret_cast<void*>(high),i*4)!=(cells[i]&0x380))r.geometry_mismatches.fetch_add(1);
        if(r.geometry_mismatches.load()){fail(30);cleanup(true);return;}
        if(!text_equals(c,static_cast<unsigned char*>(layout)+8,"sc/level_dragon_arena_dl.sc")||
           !text_equals(c,static_cast<unsigned char*>(layout)+0x18,"dragon_base_01")){fail(31);cleanup(true);return;}
        audit(private_map::GEOMETRY_CHECKED);
        if(consumer&&!consumer(consumer_context,layout)){fail(83);return;}
        cleanup(false);
    } catch(...) {
        r.failure.store(parser_started?99:98);r.stage.store(private_map::EXCEPTION);
        // Retain exact addresses. An exception may have interrupted a native
        // constructor; no guessed destructor or module unload is authorized.
    }
}
} // namespace private_layout
