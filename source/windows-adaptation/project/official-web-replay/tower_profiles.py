"""Tower troop identities for the audited client's active public catalog.

169 is the official SupportCard category, NOT the web/API's159 category.
Every mapping must also be confirmed against live public resource evidence.
Inactive Goblin Queen mode support is not an interchangeable ladder tower.
"""
TOWERS={
    'tower-princess':dict(support_id=169000000,name='King_PrincessTowers',character='PrincessTower',king_character='KingTower'),
    'cannoneer':dict(support_id=169000001,name='King_CannonTowers',character='Cannoneer',king_character='KingTower'),
    'dagger-duchess':dict(support_id=169000002,name='King_KnifeTowers',character='DaggerDuchess',king_character='KingTower'),
    'royal-chef':dict(support_id=169000004,name='King_ChefTowers',character='ChefTower',king_character='ChefTowerKing'),
}
# Native initialization receipts bootstrap-v50..53 (both owners, level16),
# not a Princess HP substitution or a value used to alter engine output.
TOWER_HP_16={'tower-princess':4858,'cannoneer':4164,'dagger-duchess':4406,'royal-chef':4302}


def tower_key(key):
    if key not in TOWERS:raise ValueError('当前原生版本没有已验证的塔楼部队：'+str(key))
    return key


def tower_request(tower,evidence):
    key=tower_key(tower.get('card_key'));level=tower.get('level')
    if type(level) is not int or not 1<=level<=16:raise ValueError('塔楼等级缺失或不受当前版本支持')
    row=next((r for r in evidence if r['card_key']==key),None)
    if row is None:raise ValueError('需要当前客户端的塔楼目录校验：'+key)
    if any(row[k]!=TOWERS[key][k] for k in ('support_id','name')):
        raise ValueError('塔楼来源与当前原生目录不一致')
    internal=level-1-row['relative_level']
    if not 0<=internal<row['level_count']:raise ValueError('塔楼等级超出其原生稀有度范围')
    spawns=row['spawn_entries']
    expected=TOWERS[key]
    if len(spawns)!=3 or [(e['name'],e['grid_x'],e['grid_y'],e['side_filter']) for e in spawns]!=[
            (expected['king_character'],18,6,-1),(expected['character'],7,13,-1),(expected['character'],29,13,-1)]:
        raise ValueError('塔楼出生组与原生天梯布局不一致')
    if any(type(e['data_id']) is not int or not -(1<<31)<=e['data_id']<(1<<31) for e in spawns):
        raise ValueError('塔楼定义编号无效')
    return dict(card_key=key,source_level=level,support_id=row['support_id'],internal_level=internal,
                relative_level=row['relative_level'],spawn_entries=row['spawn_entries'])


def default_binding(level=16):
    """Keep historical, already native-verified Princess16 input compatible."""
    return tower_request(dict(card_key='tower-princess',level=level),[dict(card_key='tower-princess',
        support_id=169000000,name='King_PrincessTowers',relative_level=0,level_count=16,
        spawn_entries=[dict(data_id=35000000 if i==0 else 35000001,
                            name='KingTower' if i==0 else 'PrincessTower',
                            grid_x=x,grid_y=y,side_filter=-1) for i,(x,y) in enumerate(((18,6),(7,13),(29,13)))])])


def bindings(doc):
    rows=doc.get('tower_bindings')
    if rows is None:return [default_binding(),default_binding()]
    if len(rows)!=2:raise ValueError('two tower bindings required')
    for row in rows:
        key=tower_key(row['card_key'])
        if type(row['source_level']) is not int or not 1<=row['source_level']<=16 or row['support_id']!=TOWERS[key]['support_id']:
            raise ValueError('tower binding must preserve source level/type')
        relative={'tower-princess':0,'cannoneer':5,'dagger-duchess':8,'royal-chef':8}[key]
        if row['relative_level']!=relative or row['internal_level']+relative!=row['source_level']-1:
            raise ValueError('tower rarity level changed')
        tower_request(dict(card_key=key,level=row['source_level']),[dict(row,name=TOWERS[key]['name'],level_count=16-relative)])
        king=row.get('king_level',row['source_level'])
        if type(king) is not int or not 1<=king<=16:raise ValueError('invalid king level')
    return rows


def oracle_tower_entries(doc,owner):
    """Page slots follow native spawn order for either owner: x3500, x14500.

    Owner controls side membership, not another horizontal mirroring. The
    asymmetric two-survivor 08CY0LPY90V0 receipt proves owner0's sequence:
    page [3408,4275] is native x3500=3408, x14500=4275. Never choose an order
    based on which one minimizes HP difference. A missing/dead entry remains
    subject to the separately documented compact-survivor rule.
    """
    if type(owner) is not int or owner not in (0,1):raise ValueError('invalid tower owner')
    for key,entry in zip(('king','princess0','princess1'),bindings(doc)[owner]['spawn_entries']):
        yield key,dict(entry)


def oracle_tower_pairs(deck,preparation,state):
    """Retain surviving princess order, never sort HP or exchange opponents.

    The battle-log princess HP array omits destroyed towers. Its one-element
    form cannot identify which side fell. hp-popup pads the absent entry to 0.
    Keep fixed native spawn order while both survive; after a loss compare the
    surviving sequence and destruction count, without certifying the dead side.
    """
    owner=deck['proposed_native_owner'];oracle=deck.get('oracle_final_hp') or {}
    keys=('king','princess0','princess1')
    if any(type(oracle.get(key)) is not int or oracle[key]<0 for key in keys):return None
    alive=state.get('towers',[])
    destroyed=[t for t in state.get('destroyed_towers',[]) if t.get('native_destructor_observed') is True and t.get('hp')==0]
    king_entry=bindings(preparation)[owner]['spawn_entries'][0]
    king_id=king_entry['data_id']&0xffffffff
    king_fell=any(t['owner']==owner and t['data_id']&0xffffffff==king_id and t['hp']==0 for t in alive+destroyed)
    actual=[]
    for key,entry in oracle_tower_entries(preparation,owner):
        spot=(owner,entry['data_id']&0xffffffff,entry['grid_x']*500)
        found=[t for t in alive if (t['owner'],t['data_id']&0xffffffff,t['x'])==spot]
        gone=[t for t in destroyed if (t['owner'],t['data_id']&0xffffffff,t['x'])==spot]
        if len(found)>1 or (found and gone):return None
        if found:hp=found[0]['hp']
        elif gone or (key!='king' and king_fell):hp=0
        else:return None
        if type(hp) is not int or hp<0:return None
        actual.append(hp)
    expected_pair=[oracle[key] for key in keys[1:] if oracle[key]>0]
    actual_pair=[hp for hp in actual[1:] if hp>0]
    expected_pair += [0]*(2-len(expected_pair));actual_pair += [0]*(2-len(actual_pair))
    return [('king',oracle['king'],actual[0])]+[(key,expected,observed) for key,expected,observed in zip(keys[1:],expected_pair,actual_pair)]


def render_towers(doc,prefix):
    rows=bindings(doc)
    text='struct ExpectedTower{unsigned id;int x,y,level,hp;bool king;};\n'
    text+='static const ExpectedTower '+prefix+'_towers[2][3]={'
    owners=[]
    for owner,row in enumerate(rows):
        items=[]
        for i,spawn in enumerate(row['spawn_entries']):
            x,y=spawn['grid_x']*500,spawn['grid_y']*500
            if owner==1:y=32000-y
            level=row.get('king_level',row['source_level']) if i==0 else row['source_level']
            # Lower-level HP comes from the engine, not an approximate growth
            # formula. Initialization verifies type/level/full health and binds
            # its exact value for all subsequent simulations and the scene.
            hp=(7728 if i==0 else TOWER_HP_16[row['card_key']]) if level==16 else 0
            captured=doc.get('native_initial_tower_hp')
            if captured is not None:hp=captured[owner][i]
            items.append('{'+','.join(map(str,(spawn['data_id']&0xffffffff,x,y,level-1,hp)))+','+str(i==0).lower()+'}')
        owners.append('{'+','.join(items)+'}')
    text+=','.join(owners)+'};\n'
    text+='static const unsigned '+prefix+'_support[2][3]={'+','.join('{'+str(r['support_id'])+','+str(r['internal_level'])+','+str(int(r.get('explicit_support',r['card_key']!='tower-princess')))+'}' for r in rows)+'};\n'
    return text


def bind_initial_towers(doc,receipt):
    """Bind full-health evidence from a clean initialization, not final HP."""
    import copy
    released=receipt.get('component_unloaded') or (receipt.get('observer_released') is True
        and receipt.get('mumu_module_retained_safe') is True and receipt.get('module_retained_for_translated_return_safety') is True)
    if not receipt.get('source_bootstrap_verified') or receipt.get('errors') or not released or not receipt.get('detached'):
        raise ValueError('tower initialization was not safely verified')
    rows=bindings(doc);values=receipt.get('initial_towers',[])
    if len(values)!=6:raise ValueError('six initial native towers required')
    hp=[[0]*3 for _ in range(2)]
    for value in values:
        owner=value['owner']
        if type(owner) is not int or owner not in (0,1):raise ValueError('invalid tower owner')
        row=rows[owner];matches=[]
        for i,spawn in enumerate(row['spawn_entries']):
            level=row.get('king_level',row['source_level']) if i==0 else row['source_level']
            y=spawn['grid_y']*500;y=32000-y if owner else y
            if (value['data_id'],value['x'],value['y'],value['level_index'],value['king'])==(spawn['data_id']&0xffffffff,spawn['grid_x']*500,y,level-1,int(i==0)):matches.append(i)
        if len(matches)!=1:raise ValueError('initial tower identity or level differs')
        i=matches[0];health=value['hp']
        if hp[owner][i] or type(health) is not int or not 0<health<=50000 or health!=value['max_hp']:raise ValueError('initial tower health differs')
        hp[owner][i]=health
    result=copy.deepcopy(doc);result['native_initial_tower_hp']=hp
    return result
