"""Recorded observer shim; audited original native headers remain byte intact."""
import hashlib
from pathlib import Path


def adapt_header(original,prefix):
    if prefix not in ('bootstrap','scene'):raise ValueError('unknown tower input')
    helper='''inline bool mumu_expected_tower(uintptr_t object,unsigned id){
    const int owner=field<int>(object+0x78);
    if(owner<0||owner>1)return false;
    const int x=field<int>(object+0x7c),y=field<int>(object+0x80);
    for(const auto& expected:PREFIX_towers[owner])
        if(id==expected.id&&x==expected.x&&y==expected.y)return true;
    return false;
}
'''.replace('PREFIX',prefix)
    # Both diagnostic reads and destructor-watch setup must use the same exact
    # source/owner/coordinate-bound identities, including unsigned hashed IDs.
    edits=[('struct ReadRanges {',helper+'struct ReadRanges {'),
        ('if(id/1000000!=35)continue;','if(!mumu_expected_tower(object,static_cast<unsigned>(id)))continue;'),
        ('std::to_string(w.id)','std::to_string(static_cast<unsigned>(w.id))')]
    result=original
    for old,new in edits:
        wanted=2 if old=='if(id/1000000!=35)continue;' else 1
        if result.count(old)!=wanted:raise ValueError('audited tower observer anchor changed: '+old)
        result=result.replace(old,new)
    old='if(result.tower_watch_count>=6||!c.readable(c.base+0x1c26f70,1024))return false;'
    new='''for(unsigned k=0;k<result.tower_watch_count;++k){const auto& seen=result.tower_watch[k];
                if(seen.health==health||(seen.owner==field<int>(object+0x78)&&
                   static_cast<unsigned>(seen.id)==static_cast<unsigned>(id)&&
                   seen.x==field<int>(object+0x7c)&&seen.y==field<int>(object+0x80)))return false;
            }
            '''+old
    if result.count(old)!=1:raise ValueError('audited tower uniqueness guard changed')
    result=result.replace(old,new)
    old='if(!memory.refresh()||!watch_towers(c,result,d)){result.error=119;active_trace=nullptr;current_ranges=nullptr;return;}'
    new='''if(!memory.refresh()||!watch_towers(c,result,d)){
        result.error=119;active_trace=nullptr;current_ranges=nullptr;
        result.text="{\\"error\\":119,\\"event_index\\":0,\\"tick\\":0,\\"native_code\\":0,\\"executed\\":0,\\"native_accepted\\":0,\\"finished\\":false,\\"commands\\":[],\\"diagnostics\\":[],\\"watched_tower_count\\":"+std::to_string(result.tower_watch_count)+"}";
        return;
    }'''
    if result.count(old)!=1:raise ValueError('audited tower failure branch changed')
    return result.replace(old,new)


def write_header(source,out,prefix,preparation=None):
    original=(source.parent/'source_execution.h').read_bytes()
    adapted=adapt_header(original.decode('utf-8'),prefix)
    from mumu_skill_observer import adapt_header as adapt_skills
    adapted,skills=adapt_skills(adapted,prefix,preparation or {})
    adapted=adapted.encode('utf-8')
    path=out/'mumu_source_execution.h';path.write_bytes(adapted)
    return path,{'policy':'verified-owner-id-position-v1','original_header_sha256':hashlib.sha256(original).hexdigest(),
        'generated_header_sha256':hashlib.sha256(adapted).hexdigest(),
        'types_from':'fresh verified native tower input','six_towers_required':True,
        'health_vtable_and_destructor_guards_preserved':True,'original_header_changed':False,'skill_and_hp_observer':skills}
