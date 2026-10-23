"""Recorded private-simulation identity/floor observers; original C++ is intact."""
import json,re

def adapt_header(text,prefix,doc):
    floors=doc.get('oracle_tower_hp')
    if floors is None:return text,{'enabled':False}
    if not isinstance(floors,list) or len(floors)!=2 or any(not isinstance(r,list) or len(r)!=3 or any(type(v)is not int or not 0<=v<=50000 for v in r) for r in floors):raise ValueError('invalid source tower floors')
    names=doc.get('ability_actor_names',{})
    if not isinstance(names,dict) or any(not isinstance(k,str) or not k.isdigit() or not 0<=int(k)<len(doc['events']) or doc['events'][int(k)]['kind']!='activate_ability' or not isinstance(v,str) or not re.fullmatch('[A-Za-z0-9_]{1,64}',v) for k,v in names.items()):raise ValueError('invalid native ability identity constraint')
    prune=doc.get('prune_below_oracle',True)
    if type(prune)is not bool:raise ValueError('invalid floor pruning policy')
    checkpoint=doc.get('skill_checkpoint_tick',-1)
    if type(checkpoint)is not int or (checkpoint!=-1 and not 100<=checkpoint<=6000):raise ValueError('invalid checkpoint tick')
    stop_checkpoint=doc.get('stop_at_skill_checkpoint',True)
    if type(stop_checkpoint)is not bool:raise ValueError('invalid checkpoint stop policy')
    helper=r'''
static constexpr int mumu_oracle_hp[2][3]=FLOORS;
static constexpr bool mumu_prune_floor=PRUNE;
static constexpr int mumu_checkpoint_tick=CHECKPOINT;
static constexpr bool mumu_stop_checkpoint=STOPCHECK;
struct MuMuActorRequirement{int index;const char* name;};
static const MuMuActorRequirement mumu_actor_requirements[]={REQUIREMENTS{-1,nullptr}};
inline const char* mumu_required_actor(int index){for(const auto& r:mumu_actor_requirements)if(r.index==index)return r.name;return nullptr;}
inline std::string mumu_actor_name(const Calls& c,uintptr_t object){
    if(!c.readable(object,0x88))return "";
    const auto def=field<uintptr_t>(object+0x48);if(!c.readable(def,0x44))return "";
    const int size=field<int>(def+0x2c);if(size<1||size>64)return "";
    auto bytes=size<8?def+0x30:field<uintptr_t>(def+0x30);
    if(!c.readable(bytes,size))return "";
    std::string value(reinterpret_cast<const char*>(bytes),size);
    for(char ch:value)if(!((ch>='a'&&ch<='z')||(ch>='A'&&ch<='Z')||(ch>='0'&&ch<='9')||ch=='_'))return "";
    return value;
}
inline void mumu_record_actors(const Calls& c,Result& r,int index,const std::vector<uintptr_t>& actors,const char* phase,int selected=-1){
    if(r.mumu_abilities.size()>131072){r.error=125;return;}
    if(r.mumu_abilities.size()>1)r.mumu_abilities+=',';
    r.mumu_abilities+="{\"event_index\":"+std::to_string(index)+",\"phase\":\""+phase+"\",\"selected_ordinal\":"+std::to_string(selected)+",\"actors\":[";
    bool first=true;for(auto actor:actors){
        if(!first)r.mumu_abilities+=',';first=false;
        auto def=field<uintptr_t>(actor+0x48);
        auto ability=c.readable(def,0x728)?field<uintptr_t>(def+0x720):0;
        int cost=ability&&c.readable(ability,0xb8)?field<int>(ability+0xb4):-1;
        r.mumu_abilities+="{\"name\":\""+mumu_actor_name(c,actor)+"\",\"definition_id\":"+std::to_string(field<unsigned>(def+0x40))+",\"cost\":"+std::to_string(cost)+"}";
    }r.mumu_abilities+="]}";
}
inline bool mumu_check_hp_floor(const Calls& c,Result& r,int tick){
    if(r.mumu_floor!="null")return !mumu_prune_floor;
    int hp[2][3]{};bool seen[2][3]{};
    for(const auto& w:r.tower_watch){
        if(w.owner<0||w.owner>1){r.error=125;return false;}
        int slot=-1;for(int k=0;k<3;++k){const auto& t=PREFIX_towers[w.owner][k];if(static_cast<unsigned>(w.id)==t.id&&w.x==t.x&&w.y==t.y)slot=k;}
        if(slot<0||seen[w.owner][slot]){r.error=125;return false;}seen[w.owner][slot]=true;
        if(!w.destroyed){
            if(!c.readable(w.health,0x28)||field<uintptr_t>(w.health)!=reinterpret_cast<uintptr_t>(w.table)){r.error=125;return false;}
            hp[w.owner][slot]=field<int>(w.health+0x10);
        }
    }
    for(int o=0;o<2;++o)for(int k=0;k<3;++k)if(!seen[o][k]){r.error=125;return false;}
    if(mumu_checkpoint_tick>=0&&(tick==mumu_checkpoint_tick-40||tick==mumu_checkpoint_tick-20||tick==mumu_checkpoint_tick)){
        if(r.mumu_checkpoints.size()>1)r.mumu_checkpoints+=',';
        r.mumu_checkpoints+="{\"native_tick\":"+std::to_string(tick)+",\"all_tower_hp\":[";
        for(int o=0;o<2;++o){if(o)r.mumu_checkpoints+=',';r.mumu_checkpoints+='[';for(int k=0;k<3;++k){if(k)r.mumu_checkpoints+=',';r.mumu_checkpoints+=std::to_string(hp[o][k]);}r.mumu_checkpoints+=']';}r.mumu_checkpoints+="]}";
    }
    for(int o=0;o<2;++o){
        const auto& e=mumu_oracle_hp[o];int slot=-1,expected=0,actual=0;
        if(hp[o][0]<e[0]){slot=0;expected=e[0];actual=hp[o][0];}
        else if(e[1]>0&&e[2]>0){for(int k=1;k<3;++k)if(hp[o][k]<e[k]){slot=k;expected=e[k];actual=hp[o][k];break;}}
        else if((e[1]>0)!=(e[2]>0)){expected=e[1]>0?e[1]:e[2];actual=hp[o][1]>hp[o][2]?hp[o][1]:hp[o][2];if(actual<expected)slot=3;}
        if(slot<0)continue;
        r.mumu_floor="{\"native_tick\":"+std::to_string(tick)+",\"owner\":"+std::to_string(o)+",\"tower_slot\":"+std::to_string(slot)+",\"expected_min\":"+std::to_string(expected)+",\"actual_hp\":"+std::to_string(actual)+",\"all_tower_hp\":[";
        for(int s=0;s<2;++s){if(s)r.mumu_floor+=',';r.mumu_floor+='[';for(int k=0;k<3;++k){if(k)r.mumu_floor+=',';r.mumu_floor+=std::to_string(hp[s][k]);}r.mumu_floor+=']';}r.mumu_floor+="]}";
        return !mumu_prune_floor;
    }
    if(mumu_stop_checkpoint&&mumu_checkpoint_tick>=0&&tick==mumu_checkpoint_tick){r.error=126;return false;}
    return true;
}
'''.replace('FLOORS','{'+','.join('{'+','.join(map(str,r))+'}' for r in floors)+'}').replace('PRUNE',str(prune).lower()).replace('CHECKPOINT',str(checkpoint)).replace('STOPCHECK',str(stop_checkpoint).lower()).replace('PREFIX',prefix).replace('REQUIREMENTS',''.join('{'+str(int(k))+','+json.dumps(v)+'},' for k,v in sorted(names.items())))
    edits=[('struct Result {std::string text;','struct Result {std::string text;std::string mumu_abilities{"["},mumu_floor{"null"},mumu_checkpoints{"["};'),
        ('inline bool bounded_read(uintptr_t p,size_t n){return current_ranges&&current_ranges->contains(p,n);}', 'inline bool bounded_read(uintptr_t p,size_t n){return current_ranges&&current_ranges->contains(p,n);}\n'+helper),
        ('            if(eligible!=1){',r'''            mumu_record_actors(c,result,result.event_index,actors,"available");
            const char* mumu_required=mumu_required_actor(result.event_index);
            const bool mumu_forced=mumu_required!=nullptr;
            if(mumu_forced){std::vector<uintptr_t> filtered;for(auto a:actors)if(mumu_actor_name(c,a)==mumu_required)filtered.push_back(a);actors=filtered;eligible=actors.size();if(eligible==1)actor=actors[0];}
            mumu_record_actors(c,result,result.event_index,actors,"eligible");
            if(eligible!=1){'''),
        ('}else if(event.ability_choice>0){','}else if(!mumu_forced&&event.ability_choice>0){'),
        ('            command=malloc(56);',r'''            int mumu_selected=-1;for(unsigned k=0;k<actors.size();++k)if(actors[k]==actor)mumu_selected=k;
            mumu_record_actors(c,result,result.event_index,actors,"selected",mumu_selected);
            command=malloc(56);'''),
        ('            if(field<int>(d+0x60)!=before+1){result.error=102;return false;}', '            if(field<int>(d+0x60)!=before+1){result.error=102;return false;}\n            if(!mumu_check_hp_floor(c,result,before+1)){if(!result.error)result.error=123;return false;}')]
    for old,new in edits:
        if 'mumu_record_actors(c,result' in new:new=new.replace('\\"','"')
        if text.count(old)!=1:raise ValueError('audited skill/floor anchor changed: '+old)
        text=text.replace(old,new)
    old='",\\"dispatch\\":"+dispatch+\'}\';'
    at=text.rfind(old)
    if at<0:raise ValueError('audited result JSON anchor changed')
    text=text[:at]+text[at:].replace(old,'",\\"dispatch\\":"+dispatch+",\\"ability_observations\\":"+result.mumu_abilities+"],\\"hp_floor_violation\\":"+result.mumu_floor+",\\"skill_checkpoints\\":"+result.mumu_checkpoints+"]"+\'}\';',1)
    return text,dict(enabled=True,prune_below_oracle=prune,oracle_tower_hp=floors,ability_actor_names=names,checkpoint_tick=checkpoint,stop_at_checkpoint=stop_checkpoint,original_engine_validation_preserved=True)
