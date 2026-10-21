"""Receipt ownership must precede the app-visible terminal status rename."""
import ast,json,os,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
SOURCE=Path(__file__).resolve().parents[1]/'device/device_playback.py'
tree=ast.parse(SOURCE.read_text(encoding='utf-8'))
nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='publish_private_receipts']
scope={'os':os};exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),'exec'),scope)
publish=scope['publish_private_receipts']
class PrivateReceiptTests(unittest.TestCase):
 def test_nested_root_receipts_are_transferred_without_world_access(self):
  with tempfile.TemporaryDirectory() as raw:
   directory=Path(raw);nested=directory/'debugger';nested.mkdir();receipt=nested/'terminal.json';receipt.write_text('{}');calls=[]
   with patch.object(os,'chown',side_effect=lambda p,u,g:calls.append((p,u,g)),create=True):publish(directory,types.SimpleNamespace(st_uid=10048,st_gid=10048))
   self.assertEqual({p for p,_,_ in calls},{directory,nested,receipt})
   self.assertTrue(all((u,g)==(10048,10048) for _,u,g in calls))
 def test_symlink_is_rejected_before_any_ownership_change(self):
  with tempfile.TemporaryDirectory() as raw:
   directory=Path(raw);receipt=directory/'terminal.json';receipt.write_text('{}')
   with patch.object(Path,'is_symlink',lambda p:p==receipt),patch.object(os,'chown',create=True) as chown:
    with self.assertRaisesRegex(ValueError,'unexpected link'):publish(directory,types.SimpleNamespace(st_uid=10048,st_gid=10048))
    chown.assert_not_called()
 def test_app_cannot_observe_terminal_state_before_receipts(self):
  # Execute the real nested publisher with deterministic time and a real temp
  # status file. Mock chown observes the old state until ownership is ready.
  run=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run')
  status=next(n for n in run.body if isinstance(n,ast.FunctionDef) and n.name=='status')
  outer=ast.FunctionDef(name='make_status',args=ast.arguments(posonlyargs=[],args=[ast.arg(arg=n) for n in ('destination','owner','context')],kwonlyargs=[],kw_defaults=[],defaults=[]),
   body=ast.parse('started=0\nphase_started=0\nphase_name=None\nphase_totals={}').body+[status,ast.Return(value=ast.Name(id='status',ctx=ast.Load()))],decorator_list=[])
  scope2={'publish_private_receipts':publish,'time':types.SimpleNamespace(monotonic=lambda:1,time=lambda:2),'json':json,'os':os}
  module=ast.fix_missing_locations(ast.Module(body=[outer],type_ignores=[]));exec(compile(module,str(SOURCE),'exec'),scope2)
  with tempfile.TemporaryDirectory() as raw:
   directory=Path(raw);terminal=directory/'scene-v1-terminal-result.json';terminal.write_text('{}');(directory/'status.json').write_text('{"state":"returning_lobby"}')
   checked=[]
   def ownership(p,u,g):
    if p==terminal:checked.append(json.loads((directory/'status.json').read_text())['state'])
   with patch.object(os,'chown',side_effect=ownership,create=True):
    scope2['make_status'](directory,types.SimpleNamespace(st_uid=10048,st_gid=10048),{'monitor_active':True})('complete','done',monitor_active=False)
   self.assertEqual(checked,['returning_lobby'])
   self.assertTrue(json.loads((directory/'status.json').read_text())['private_receipts_published'])
if __name__=='__main__':unittest.main()
