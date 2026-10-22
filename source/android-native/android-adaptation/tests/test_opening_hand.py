from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'official-web-replay'))
from prepare_native_replay import NOT_IN_OPENING, cycle_slots, infer_compatible_cycle  # noqa: E402

COLLECTOR,MIRROR=27000007,28000006


class OpeningHandTests(unittest.TestCase):
    def test_the_catalog_and_the_rule_name_the_same_two_cards(self):
        import json
        # The catalog sits beside this tree locally and one level up in the published repo.
        paths=[base/'windows-adaptation/project/vendor/native_runner/card-aliases.json' for base in (ROOT.parent,ROOT.parent.parent)]
        path=next((p for p in paths if p.is_file()),None)
        if path is None:self.skipTest('card catalog not present')
        catalog=json.loads(path.read_text())
        rows=catalog if isinstance(catalog,list) else catalog.get('cards',[])
        self.assertEqual(sorted(r['card_id'] for r in rows if isinstance(r,dict) and r.get('omit_from_starting_hand')),sorted(NOT_IN_OPENING))

    def test_collector_seen_early_is_moved_to_the_fifth_card(self):
        cards=[1,2,3,COLLECTOR,5,6,7,8]
        plays=[1,2,COLLECTOR,3,5,1,6]  # Collector is the third distinct card played
        cycle=infer_compatible_cycle(cards,plays)
        self.assertNotIn(COLLECTOR,cycle['opening'])
        self.assertEqual(cycle['opening'],[1,2,3,5])
        self.assertEqual(cycle['queue'][0],COLLECTOR)  # the 5th card
        self.assertIsNotNone(cycle_slots(cycle['opening'],cycle['queue'],plays))

    def test_collector_and_mirror_take_the_fifth_and_sixth_cards(self):
        cards=[1,2,MIRROR,3,COLLECTOR,6,7,8]
        plays=[1,MIRROR,2,3,6]
        cycle=infer_compatible_cycle(cards,plays)
        self.assertEqual(cycle['opening'],[1,2,3,6])
        self.assertEqual(set(cycle['queue'][:2]),{MIRROR,COLLECTOR})

    def test_decks_without_them_keep_the_first_four_distinct_plays(self):
        cycle=infer_compatible_cycle([1,2,3,4,5,6,7,8],[3,1,4,5,2,6])
        self.assertEqual(cycle['opening'],[3,1,4,5])
        with self.assertRaises(ValueError):infer_compatible_cycle([1,2,3,4,5,6,7,8],[1,2,1])

    def test_recalibration_never_deals_them_in_the_opening(self):
        text=(ROOT.parent/'official-web-replay/align_native_deal.py').read_text()
        self.assertIn('if set(actual[:4])&set(NOT_IN_OPENING):slots=None',text)
        self.assertIn('if set(opening)&set(NOT_IN_OPENING):continue',text)


RAGE,WITCH,GIANT,MPK,ZAP,DP,ARROWS=28000002,26000007,26000003,26000018,28000008,26000027,28000001


class NativeDealModelTests(unittest.TestCase):
    """Real observations from 08UPYGRCGVRC on MuMu (deck0, Collector played 2nd)."""
    def setUp(self):
        # Other tests replace tower_profiles with a stand-in; this module needs the real one.
        if not getattr(sys.modules.get('tower_profiles'),'__file__',None):sys.modules.pop('tower_profiles',None)
        sys.modules.pop('align_native_deal',None)

    def test_one_seed_explains_every_observed_deal(self):
        from align_native_deal import engine_draws,engine_deal
        observed=[([WITCH,GIANT,MPK,ZAP,DP,RAGE,COLLECTOR,ARROWS],[DP,WITCH,MPK,ZAP,RAGE,GIANT,COLLECTOR,ARROWS]),
                  ([WITCH,GIANT,MPK,ZAP,RAGE,COLLECTOR,DP,ARROWS],[RAGE,WITCH,MPK,ZAP,DP,GIANT,COLLECTOR,ARROWS]),
                  ([WITCH,GIANT,MPK,ARROWS,RAGE,COLLECTOR,ZAP,DP],[RAGE,WITCH,MPK,ARROWS,ZAP,GIANT,COLLECTOR,DP])]
        draws=engine_draws(*observed[0])
        self.assertEqual(draws,[4,0,1,1,1,0,1,0])
        for physical,dealt in observed:self.assertEqual(engine_deal(physical,draws),dealt)
        # A fixed deck-position permutation cannot explain them; the set-aside rule does.
        self.assertIsNone(engine_draws([COLLECTOR,WITCH,GIANT,MPK,ZAP,DP,RAGE,ARROWS],[COLLECTOR,WITCH,GIANT,MPK,ZAP,DP,RAGE,ARROWS]))

    def test_deck_order_is_solved_directly(self):
        from align_native_deal import engine_deal,deck_order_for
        draws=[4,0,1,1,3,0,1,0]  # a seed that deals the 5th card from the end: Collector 5th
        desired=[RAGE,WITCH,GIANT,MPK,COLLECTOR,ZAP,DP,ARROWS]
        deck=deck_order_for(desired,draws)
        self.assertEqual(engine_deal(deck,draws),desired)
        self.assertIsNone(deck_order_for(desired,[4,0,1,1,1,0,1,0]))  # this seed puts Collector 7th

    def test_a_seed_that_cannot_place_collector_asks_for_another_seed(self):
        from align_native_deal import calibrate_held,DEAL_SEED_INFEASIBLE
        entries=[dict(d=c) for c in [WITCH,GIANT,MPK,ZAP,DP,RAGE,COLLECTOR,ARROWS]]
        actual=[DP,WITCH,MPK,ZAP,RAGE,GIANT,COLLECTOR,ARROWS]
        plays=[RAGE,COLLECTOR,GIANT,WITCH,MPK,RAGE,ZAP,DP,WITCH]  # the page: Collector 2nd
        with self.assertRaises(ValueError) as caught:
            calibrate_held(entries,actual,None,plays,[RAGE,WITCH,MPK,ZAP,COLLECTOR,GIANT,DP,ARROWS],[],0)
        self.assertIn(DEAL_SEED_INFEASIBLE,str(caught.exception))
        playback=(ROOT/'device/device_playback.py').read_text()
        self.assertIn('if DEAL_SEED_INFEASIBLE not in str(error):raise',playback)
        self.assertIn("random_seed_inferred=seed_report['selected_seed']!=original_seed or bool(context.get('deal_seed_changed'))",playback)

    def test_a_feasible_seed_gives_a_legal_deal_in_one_step(self):
        from align_native_deal import calibrate_held,engine_deal
        draws=[4,0,1,1,3,0,1,0]
        physical=[WITCH,GIANT,MPK,ZAP,DP,RAGE,COLLECTOR,ARROWS]
        actual=engine_deal(physical,draws)
        entries=[dict(d=c) for c in physical]
        plays=[RAGE,COLLECTOR,GIANT,WITCH,MPK,RAGE,ZAP,DP,WITCH]
        deck,desired,slots=calibrate_held(entries,actual,None,plays,list(actual),[],0)
        self.assertEqual(engine_deal([c['d'] for c in deck],draws),desired)
        self.assertEqual(desired[4],COLLECTOR);self.assertNotIn(COLLECTOR,desired[:4])
        self.assertIsNotNone(cycle_slots(desired[:4],desired[4:],plays))


if __name__=='__main__':unittest.main()
