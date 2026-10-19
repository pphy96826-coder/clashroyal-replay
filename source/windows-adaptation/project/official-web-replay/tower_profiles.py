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


def default_binding():
    """Keep historical, already native-verified Princess16 input compatible."""
    return tower_request(dict(card_key='tower-princess',level=16),[dict(card_key='tower-princess',
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
        if row['source_level']!=16 or row['support_id']!=TOWERS[key]['support_id']:
            raise ValueError('tower binding must preserve the verified level16 source')
        relative={'tower-princess':0,'cannoneer':5,'dagger-duchess':8,'royal-chef':8}[key]
        if row['relative_level']!=relative or row['internal_level']+relative!=15:
            raise ValueError('tower rarity level changed')
        tower_request(dict(card_key=key,level=16),[dict(row,name=TOWERS[key]['name'],level_count=16-relative)])
    return rows


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
            hp=7728 if i==0 else TOWER_HP_16[row['card_key']]
            items.append('{'+','.join(map(str,(spawn['data_id']&0xffffffff,x,y,15,hp)))+','+str(i==0).lower()+'}')
        owners.append('{'+','.join(items)+'}')
    text+=','.join(owners)+'};\n'
    text+='static const unsigned '+prefix+'_support[2][2]={'+','.join('{'+str(r['support_id'])+','+str(r['internal_level'])+'}' for r in rows)+'};\n'
    return text
