from pathlib import Path
import ast
import unittest

ROOT=Path(__file__).resolve().parents[1]
JAVA=ROOT/'app/src/local/royale/replay/android'

class ConsoleTests(unittest.TestCase):
    def test_main_has_three_primary_and_terminal_contextual_actions(self):
        main=(JAVA/'MainActivity.java').read_text()
        self.assertEqual(main.count('button(root,'),11)  # Queue actions plus read-only diagnostic export.
        self.assertIn('添加多个 HTML 到队列',main)
        self.assertIn('queueImporting',main)
        for old in ('doctor();','localBuild();','fixture();','pairing.json','status-','请求原生播放','等待电脑'):
            self.assertNotIn(old,main)
        self.assertIn('watch.setVisibility(active?View.VISIBLE:View.GONE)',main)
        self.assertIn('stop.setVisibility(PlaybackStatus.canStop',main)
        self.assertIn('PlaybackService.submitOrQueue(MainActivity.this,bytes,speed)',main)
        self.assertIn('replay.setVisibility((complete||saved!=null)?View.VISIBLE:View.GONE)',main)
        self.assertIn('exitReplay.setVisibility(complete?View.VISIBLE:View.GONE)',main)
        self.assertIn('removeReplay.setVisibility(saved!=null?',main)
        self.assertIn('SavedReplay.load',main)
        self.assertNotIn('true);PlaybackService.openGame',main)

    def test_notification_returns_to_console_and_request_is_immutable(self):
        service=(JAVA/'PlaybackService.java').read_text()
        self.assertIn('PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE',service)
        self.assertIn('.setContentIntent(back)',service)
        self.assertIn('id+".html"',service)
        self.assertNotIn('phone-ui-source.html',service)
        self.assertIn('if(busy)throw',service)

    def test_browser_direct_is_local_to_webview_not_system(self):
        browser=(JAVA/'BrowserActivity.java').read_text()
        self.assertIn('.addDirect().removeImplicitRules()',browser)
        self.assertNotIn('getDefaultProxy()',browser)
        self.assertNotIn('settings put',browser)
        self.assertNotIn('addProxyRule(',browser)
        self.assertNotIn('clearProxyOverride',browser)
        self.assertNotIn('addJavascriptInterface',browser)
        self.assertNotIn('getCookie(',browser)
        self.assertIn('setAllowFileAccess(false)',browser)
        self.assertIn('setAllowContentAccess(false)',browser)
        self.assertIn('handle.cancel()',browser)
        self.assertIn('!tag.equals(parsed.tag)',browser)

    def test_start_does_not_jump_and_ui_handoff_is_gated(self):
        service=(JAVA/'PlaybackService.java').read_text()
        begin=service[service.index('static synchronized void begin'):service.index('static void openGame')]
        self.assertNotIn('openGame(',begin)
        handoff=(JAVA/'PlaybackHandoff.java').read_text()
        self.assertIn('NativePython.sameGameGeneration(state)',handoff)
        self.assertIn('if(!readyForForeground(current,',handoff)
        self.assertIn('openCovered(requested,current,record)',handoff)
        self.assertLess(handoff.index('PlaybackService.coverBeforeGame('),handoff.index('PlaybackService.openGame(activity)'))
        self.assertIn('if(!visible||checking||!PlaybackService.isBusy())return',handoff)
        self.assertIn('record.exists()',handoff)

    def test_overlay_has_explicit_system_consent_and_no_input_capture(self):
        access=(JAVA/'OverlayAccess.java').read_text()
        overlay=(JAVA/'ReplayOverlay.java').read_text()
        self.assertIn('Settings.canDrawOverlays',access)
        self.assertIn('Settings.ACTION_MANAGE_OVERLAY_PERMISSION',access)
        self.assertIn('FLAG_NOT_TOUCHABLE',overlay)
        self.assertIn('FLAG_NOT_FOCUSABLE',overlay)
        self.assertIn('params.alpha=0.75f',overlay)
        self.assertNotIn('appops',access.replace('root/appops',''))
        source=(ROOT/'device/device_playback.py').read_text()
        self.assertLess(source.index("token=read(signal)"),source.index("scene=probe('scene-v1'"))
        self.assertIn('if game_foreground():break',source)

    def test_device_foreground_predicate_does_not_match_a_background_task(self):
        from unittest.mock import Mock
        tree=ast.parse((ROOT/'device/device_playback.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='game_foreground')
        process=Mock();scope=dict(subprocess=process)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'foreground-test','exec'),scope)
        for text,expected in (
            ('topResumedActivity=ActivityRecord{ u0 com.tencent.tmgp.supercell.clashroyale/Game }',True),
            ('topResumedActivity=ActivityRecord{ u0 local.royale.replay.android/.MainActivity }\nbackground com.tencent.tmgp.supercell.clashroyale/Game',False),
        ):
            process.run.return_value=Mock(returncode=0,stdout=text.encode())
            self.assertEqual(scope['game_foreground'](),expected)

    def test_status_updates_do_not_mutate_native_commands(self):
        tree=ast.parse((ROOT/'device/device_playback.py').read_text())
        node=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='status')
        scope=dict(context={'monitor_active':True},time=type('Clock',(),{'time':staticmethod(lambda:100)})(),
                   destination=type('Dir',(),{})())
        self.assertIn('value.update(context);value.update(details)',ast.get_source_segment((ROOT/'device/device_playback.py').read_text(),node))
        source=(ROOT/'device/device_playback.py').read_text()
        self.assertIn('tick=current[\'tick\']',source)
        self.assertIn("monitor_active=False",source)
        self.assertEqual(source.count('apply_offset(read(preparation/\'preparation.json\'),GLOBAL_DELAY_TICKS)'),1)

if __name__=='__main__':unittest.main()
