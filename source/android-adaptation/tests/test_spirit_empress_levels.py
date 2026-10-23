"""Execute the real bounded observer on synthetic public resource graphs."""
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]


class PublicCards:
    base=0x100000000

    def __init__(self, empress=True):
        self.data={};self.verified=False;self.reads=[];self.mutate=False;self.batches=0
        self.table=self.base+(0x1bf4420 if empress else 0x1c0be40)
        self.definition=0x50000000;self.level=0x51000000
        self.ids=[28000025 if empress else 26000044,28000008]
        self.pointer(self.base+0x1d34ae0,0x40000000)
        self.pointer(0x40000000+0x20,0x40001000)
        self.pointer(0x40001000+0x38,0x40002000)
        self.pointer(0x40002000,self.base+0x1c04150)
        self.pointer(0x40002000+0xb8,0x40003000)
        self.put(0x40002000+0xc4,struct.pack('<i',138))
        definitions=[self.definition+0x1000*i for i in range(138)]
        self.put(0x40003000,struct.pack('<138Q',*definitions))
        for i,d in enumerate(definitions):
            self.put(d+0x40,struct.pack('<i',self.ids[i] if i<2 else 29000000+i))
        for i in (0,1):
            d=definitions[i];level=self.level+i*0x1000
            self.pointer(d,self.table if i==0 else self.base+0x1c0be40)
            self.pointer(d+0xa0,level)
            self.pointer(level,self.base+0x1c0a098)
            self.put(level+0x230,struct.pack('<ii',8 if empress and i==0 else 0,2))
        for table in (0x1c0be40,0x1bf4420):self.pointer(self.base+table+0x100,self.base+0x10cc890)
        for slot,va in ((0x118,0x10b1030),(0x120,0x10b1038)):
            self.pointer(self.base+0x1c0a098+slot,self.base+va)
        for va,code in ((0x10cc890,'005040f9c0035fd6'),(0x10b1030,'003042b9c0035fd6'),(0x10b1038,'003442b9c0035fd6')):
            self.put(self.base+va,bytes.fromhex(code))

    def put(self,address,data):
        for i,b in enumerate(data):self.data[address+i]=b

    def pointer(self,address,value):self.put(address,struct.pack('<Q',value))

    def read(self,address,size):
        self.reads.append((address,size))
        return bytes(self.data[address+i] for i in range(size))

    def read_many(self,ranges):
        self.batches+=1
        if self.mutate and self.batches==6:self.pointer(self.definition,self.base+0x1c0be40)
        return [self.read(a,n) for a,n in ranges]

    def verify(self):self.verified=True


class SpiritEmpressLevelsTests(unittest.TestCase):
    def observe(self, graph):
        spec=importlib.util.spec_from_file_location('empress_levels',ROOT/'windows-adaptation/project/official-web-replay/observe_card_levels.py')
        module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,client_session=types.SimpleNamespace(ReadOnlySession=lambda identity:graph)):
            spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            d=Path(directory);output=d/'levels.json'
            (d/'observation.json').write_text('{"identity":{}}')
            (d/'source.json').write_text(json.dumps(dict(source_sha256='a'*64,
                decks=[dict(cards=[dict(base_data_id=i) for i in graph.ids])])) )
            with patch.object(sys,'argv',['observer','--observation',str(d/'observation.json'),
                    '--source',str(d/'source.json'),'--output',str(output)]),redirect_stdout(io.StringIO()):
                try:module.main()
                except ValueError:
                    self.assertFalse(output.exists(),'failure must not publish level evidence')
                    raise
            return json.loads(output.read_text())

    def test_special_definition_reads_real_legendary_offset(self):
        graph=PublicCards();result=self.observe(graph)
        card=next(c for c in result['cards'] if c['data_id']==28000025)
        self.assertEqual((card['display_offset'],card['offset_A']),(9,8))
        self.assertEqual(card['definition_type'],'spirit-empress')
        self.assertEqual(card['definition_table_va'],'0x1bf4420')
        self.assertTrue(graph.verified)
        self.assertFalse(result['native_calls']);self.assertFalse(result['game_memory_written'])

    def test_standard_cards_remain_supported(self):
        graph=PublicCards(empress=False)
        self.assertEqual({c['data_id'] for c in self.observe(graph)['cards']},{26000044,28000008})

    def test_unknown_definition_is_not_whitelisted(self):
        graph=PublicCards();graph.pointer(graph.definition,graph.base+0x1bf4428)
        with self.assertRaisesRegex(ValueError,'card definition type changed'):self.observe(graph)

    def test_special_type_is_not_allowed_for_another_card(self):
        graph=PublicCards(empress=False);graph.pointer(graph.definition,graph.base+0x1bf4420)
        with self.assertRaisesRegex(ValueError,'card definition type changed'):self.observe(graph)

    def test_empress_with_ordinary_type_is_not_silently_accepted(self):
        graph=PublicCards();graph.pointer(graph.definition,graph.base+0x1c0be40)
        with self.assertRaisesRegex(ValueError,'card definition type changed'):self.observe(graph)

    def test_changed_inherited_callback_is_rejected(self):
        graph=PublicCards();graph.pointer(graph.table+0x100,graph.base+0x10cc898)
        with self.assertRaisesRegex(ValueError,'callback changed'):self.observe(graph)

    def test_changed_field_getter_code_is_rejected(self):
        graph=PublicCards();graph.put(graph.base+0x10b1038,b'\0'*8)
        with self.assertRaisesRegex(ValueError,'getter code changed'):self.observe(graph)

    def test_unexpected_level_source_is_rejected(self):
        graph=PublicCards();graph.pointer(graph.level,graph.base+0x1c0a100)
        with self.assertRaisesRegex(ValueError,'level source type changed'):self.observe(graph)

    def test_unsupported_offset_is_not_guessed(self):
        graph=PublicCards();graph.put(graph.level+0x230,struct.pack('<ii',99,2))
        with self.assertRaisesRegex(ValueError,'offset outside'):self.observe(graph)

    def test_generation_change_during_reread_is_rejected(self):
        graph=PublicCards();graph.mutate=True
        with self.assertRaisesRegex(ValueError,'generation changed'):self.observe(graph)

    def test_payload_refresh_carries_the_updated_observer(self):
        script=(ROOT/'android-adaptation/mumu-build/build_mumu_development_home.py').read_text()
        self.assertIn("'observe_card_levels.py'",script)


if __name__=='__main__':unittest.main()
