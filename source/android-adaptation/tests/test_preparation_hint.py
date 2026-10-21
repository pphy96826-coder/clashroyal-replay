import copy,importlib.util,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('hint_test',ROOT/'device/preparation_hint.py');hint=importlib.util.module_from_spec(spec);spec.loader.exec_module(hint)


class HintTests(unittest.TestCase):
    def setUp(self):
        self.initial={'source_sha256':'a'*64,'initialization_only':{'rndSeed':7,'battle':{'deck0':{'sp':[{'d':n,'level':16} for n in range(8)]},'deck1':{'sp':[{'d':n,'level':15} for n in range(8,16)]}}},
            'participants':{'left':{'native_owner':0,'deck_order':list(range(8)),'cycle':{'native_deal_verified':False}},'right':{'native_owner':1,'deck_order':list(range(8,16)),'cycle':{'native_deal_verified':False}}},
            'events':[{'source_side':'left','kind':'play_card','base_data_id':2,'source_tick_20hz':20,'source_position':[4,5],'native_request':{'deck_index':2,'expected_cycle_slot':1}}]}
        self.value={'schema':hint.SCHEMA,'key':'k','source_sha256':'a'*64,'seed':9,'orders':[list(reversed(range(8))),list(range(8,16))]}

    def test_only_permutation_and_seed_change_and_source_stays_immutable(self):
        before=copy.deepcopy(self.initial);result=hint.apply(self.initial,self.value,'k')
        self.assertEqual(self.initial,before)
        self.assertEqual(result['initialization_only']['battle']['deck0']['sp'],list(reversed(before['initialization_only']['battle']['deck0']['sp'])))
        self.assertEqual(result['events'][0]['native_request']['deck_index'],5)
        for name in ['source_side','kind','base_data_id','source_tick_20hz','source_position']:
            self.assertEqual(result['events'][0][name],before['events'][0][name])
        self.assertEqual(result['initialization_only']['rndSeed'],9)

    def test_cached_hint_never_claims_a_verified_native_deal(self):
        self.initial['native_deal_ready']=True
        for part in self.initial['participants'].values():part['cycle']['native_deal_verified']=True
        result=hint.apply(self.initial,self.value,'k')
        self.assertFalse(result['native_deal_ready'])
        self.assertTrue(all(not p['cycle']['native_deal_verified'] for p in result['participants'].values()))

    def test_foreign_source_schema_or_algorithm_key_refused(self):
        for key,value in [('source_sha256','b'*64),('schema','v0'),('key','other')]:
            doc=copy.deepcopy(self.value);doc[key]=value
            with self.assertRaises(ValueError):hint.apply(self.initial,doc,'k')

    def test_seed_bounds_and_types_refused(self):
        for seed in [-2**31-1,1<<31,True,'9',None]:
            doc=copy.deepcopy(self.value);doc['seed']=seed
            with self.assertRaises(ValueError):hint.apply(self.initial,doc,'k')

    def test_native_signed_seed_domain_is_preserved(self):
        self.value['seed']=-2**31
        self.assertEqual(hint.apply(self.initial,self.value,'k')['initialization_only']['rndSeed'],-2**31)

    def test_changed_missing_duplicate_or_extra_cards_refused(self):
        for order in [[0]*8,list(range(7)),list(range(9)),[99]+list(range(1,8)),[True]+list(range(1,8))]:
            doc=copy.deepcopy(self.value);doc['orders'][0]=order
            with self.assertRaises(ValueError):hint.apply(self.initial,doc,'k')

    def test_unverified_or_inexact_runs_never_save(self):
        for exact,roundtrip in [(False,True),(True,False),(False,False)]:
            self.assertFalse(hint.save(Path('unused'),self.initial,{},exact=exact,roundtrip_verified=roundtrip))
        self.assertFalse(hint.save(Path('unused'),self.initial,{},exact=True,roundtrip_verified=True))


if __name__=='__main__':unittest.main()
