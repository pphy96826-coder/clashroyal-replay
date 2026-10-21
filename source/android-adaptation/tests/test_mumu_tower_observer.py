"""All four tower catalogs, unsigned deaths, and bounded observation failures."""
import copy, importlib.util, itertools, json, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'device'))
sys.path.insert(0,str(ROOT.parent/'windows-adaptation/project/official-web-replay'))
from mumu_tower_observer import adapt_header
from native_observation import source_json, MAX_SOURCE_BYTES
from tower_profiles import TOWERS, tower_request, oracle_tower_pairs, render_towers
HEADER=ROOT.parent/'windows-adaptation/project/official-web-replay/source_execution.h'

def catalog():
    ids=[(35000000,35000001),(35000000,1485117103),(35000000,-1749071821),(1471932914,-1103717791)]
    result=[]
    for (key,row),(king,princess) in zip(TOWERS.items(),ids):
        relative={'tower-princess':0,'cannoneer':5,'dagger-duchess':8,'royal-chef':8}[key]
        result.append(dict(card_key=key,name=row['name'],support_id=row['support_id'],relative_level=relative,level_count=16-relative,
            spawn_entries=[dict(data_id=king if i==0 else princess,name=row['king_character'] if i==0 else row['character'],grid_x=x,grid_y=y,side_filter=-1)
                for i,(x,y) in enumerate(((18,6),(7,13),(29,13)))]))
    return result

class TowerObserverTests(unittest.TestCase):
    def test_generated_observer_preserves_guards_and_original(self):
        before=HEADER.read_bytes()
        for prefix in ('bootstrap','scene'):
            value=adapt_header(before.decode(),prefix)
            self.assertNotIn('id/1000000!=35',value)
            self.assertIn(prefix+'_towers[owner]',value)
            for guard in ('if(result.tower_watch_count!=6)return false;', 'field<uintptr_t>(health)!=c.base+0x1c26f70',
                'if(!unwatch_towers(c,result))result.error=120;', 'reinterpret_cast<void(*)(void*)>(method)(object);'):
                self.assertIn(guard,value)
            self.assertIn('seen.health==health',value)
            self.assertIn('std::to_string(static_cast<unsigned>(w.id))',value)
            self.assertIn('watched_tower_count',value)
        self.assertEqual(before,HEADER.read_bytes())
    def test_changed_audited_header_is_rejected(self):
        with self.assertRaises(ValueError):adapt_header(HEADER.read_text().replace('if(id/1000000!=35)continue;',''), 'bootstrap')
        with self.assertRaises(ValueError):adapt_header(HEADER.read_text(),'unknown')
    def test_all_16_pairs_both_owner_orientations(self):
        rows=catalog()
        for first,second in itertools.product(rows,repeat=2):
            prep={'tower_bindings':[tower_request({'card_key':r['card_key'],'level':16},rows) for r in (first,second)]}
            self.assertEqual(render_towers(prep,'bootstrap').count('true}'),2)
            for owner in (0,1):
                entries=prep['tower_bindings'][owner]['spawn_entries'];alive=[]
                for i,e in enumerate(entries):
                    x=e['grid_x']*500
                    alive.append(dict(owner=owner,data_id=e['data_id']&0xffffffff,x=x,hp=(7728,137,651)[i]))
                deck=dict(proposed_native_owner=owner,oracle_final_hp=dict(king=7728,princess0=137,princess1=651))
                self.assertEqual(oracle_tower_pairs(deck,prep,{'towers':alive}),[('king',7728,7728),('princess0',137,137),('princess1',651,651)])
                # Real destructor IDs may be signed or unsigned; both represent the same native ID.
                for unsigned in (False,True):
                    dead=dict(alive[1],hp=0,native_destructor_observed=True)
                    dead['data_id']=entries[1]['data_id']&0xffffffff if unsigned else entries[1]['data_id']
                    deck['oracle_final_hp'].update(princess0=651,princess1=0)
                    self.assertEqual(oracle_tower_pairs(deck,prep,{'towers':[alive[0],alive[2]],'destroyed_towers':[dead]}),
                        [('king',7728,7728),('princess0',651,651),('princess1',0,0)])
                # King's actual catalog ID determines three-crown destruction, including ChefKing.
                deck['oracle_final_hp'].update(king=0,princess0=0,princess1=0)
                king=dict(alive[0],hp=0,native_destructor_observed=True)
                self.assertEqual(oracle_tower_pairs(deck,prep,{'destroyed_towers':[king]}),[('king',0,0),('princess0',0,0),('princess1',0,0)])
                king['native_destructor_observed']=False
                self.assertIsNone(oracle_tower_pairs(deck,prep,{'destroyed_towers':[king]}))

class ObservationTests(unittest.TestCase):
    def test_empty_has_native_cause_and_does_not_read(self):
        with self.assertRaisesRegex(ValueError,'source_error=119.*watched_towers=3'):
            source_json(0,0,lambda *_:self.fail('empty read'),dict(native_source_error=119,watched_towers=3))
    def test_oversize_is_distinct_and_bounded(self):
        with self.assertRaisesRegex(ValueError,'262145 > 262144'):source_json(1,MAX_SOURCE_BYTES+1,lambda *_:self.fail('oversize read'),{})
    def test_valid_failure_is_kept(self):
        raw=b'{"error":119,"executed":0}'
        self.assertEqual(source_json(1,len(raw),lambda *_:raw,{})['error'],119)
    def test_invalid_result_cannot_become_success(self):
        for address,size,raw in [(0,2,b'{}'),(1,-1,b''),(1,3,b'{}'),(1,2,b'[]'),(1,1,b'{')]:
            with self.subTest(raw=raw),self.assertRaises((ValueError,UnicodeError)):source_json(address,size,lambda *_:raw,{})

if __name__=='__main__':unittest.main()
