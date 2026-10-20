from pathlib import Path
import ast
import unittest

ROOT=Path(__file__).resolve().parents[1]
JAVA=ROOT/'app/src/local/royale/replay/android'

class ConsoleTests(unittest.TestCase):
    def test_main_has_three_primary_and_terminal_contextual_actions(self):
        main=(JAVA/'MainActivity.java').read_text()
        self.assertEqual(main.count('button(root,'),12)  # Queue actions, floating toggle, read-only diagnostic export.
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
        self.assertIn('SavedReplay.load',(JAVA/'ConsoleActions.java').read_text())
        self.assertNotIn('true);PlaybackService.openGame',main)

    def test_floating_console_is_touchable_only_inside_and_reuses_console_gates(self):
        floating=(JAVA/'FloatingConsole.java').read_text()
        self.assertIn('FLAG_NOT_FOCUSABLE|WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL',floating)
        self.assertNotIn('FLAG_NOT_TOUCHABLE',floating)  # Its own buttons take touches; outside goes to the game.
        self.assertIn('ConsoleActions.playNext(FloatingConsole.this)',floating)
        self.assertIn('ConsoleActions.requestStop(FloatingConsole.this)',floating)
        self.assertIn('stopArmedUntil',floating)  # Stop needs a second tap.
        self.assertIn('PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE',floating)
        actions=(JAVA/'ConsoleActions.java').read_text()
        self.assertIn('else if(PlaybackStatus.ownsTask(state)){if(user)throw new IOException("当前任务尚未完成，不覆盖战斗");return;}',actions)
        self.assertIn('PlaybackService.begin(context,source,speed(),false,ReplayQueue.diagnostic(context.getFilesDir()),id)',actions)
        main=(JAVA/'MainActivity.java').read_text()
        self.assertIn('ConsoleActions.playNext(MainActivity.this)',main)
        self.assertIn('QueueRows.render(this,queueRows,',main)
        ns='{http://schemas.android.com/apk/res/android}'
        import xml.etree.ElementTree as ET
        app=ET.parse(ROOT/'app/AndroidManifest.xml').getroot().find('application')
        picker=next(a for a in app.findall('activity') if a.get(ns+'name')=='.QueueImportActivity')
        self.assertEqual(picker.get(ns+'exported'),'false')
        self.assertEqual(picker.get(ns+'taskAffinity'),'')  # Finishing returns to the game, not the console task.
        service=next(s for s in app.findall('service') if s.get(ns+'name')=='.FloatingConsole')
        self.assertEqual(service.get(ns+'exported'),'false')
        importer=(JAVA/'QueueImportActivity.java').read_text()
        self.assertLess(importer.index('ReplayQueue.importFrom'),importer.index('runOnUiThread(new Runnable(){public void run(){finish();}})'))

    def test_cancelled_preparation_restarts_only_its_own_process_on_explicit_switch(self):
        actions=(JAVA/'ConsoleActions.java').read_text()
        restart=actions[actions.index('private static void restartForRelease'):actions.index('private static boolean blockedByCancelledPreparation')]
        self.assertLess(restart.index('NativePython.sameGameGeneration(state)'),restart.index('am force-stop'))
        self.assertIn('!state.optBoolean("native_entry_started",false)',restart)
        self.assertIn('NativePython.recordRelease(context,state)',restart)
        prepare=actions[actions.index('private static void prepareHead'):actions.index('static void autoPrepare(')]
        self.assertIn('if(!user){synchronized(ConsoleActions.class){tried.put(id,pid);outcomes.put(id,"上一份准备待释放");}return;}',prepare)
        self.assertIn('blockedByCancelledPreparation(taskStatus(context))',prepare)
        ended=actions[actions.index('static void armedEnded'):actions.index('static String playNext')]
        self.assertIn('if(cancelled&&switchRequested)',ended)
        # Speed changes never cancel a prepared row; 置顶 keeps it first.
        self.assertIn('static void cycleSpeed(){speedIndex=(speedIndex+1)%SPEEDS.length;}',actions)
        self.assertIn('!armed.isEmpty()&&!armed.equals(id)?1:0',actions)
        playback=(ROOT/'device/device_playback.py').read_text()
        self.assertIn("foreground_deadline=time.monotonic()+(PREPARE_AHEAD_SECONDS if request.get('prepare_ahead') is True else 600)",playback)
        self.assertIn('.put("prepare_ahead",prepareAhead)',(JAVA/'NativePython.java').read_text())

    def test_edge_window_uses_fixed_shell_commands_only(self):
        edge=(JAVA/'EdgeWindow.java').read_text()
        self.assertIn('private static final String START="am start --windowingMode 5 -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -p "+EDGE;',edge)
        self.assertIn('StandaloneDoctor.root(START,10)',edge)
        self.assertIn('StandaloneDoctor.root("am stack list",10)',edge)
        self.assertIn('"am task resize "+Integer.parseInt(task.group(1))+" "+left+" "+top+" "+right+" "+bottom',edge)
        self.assertEqual(edge.count('StandaloneDoctor.root('),3)
        for forbidden in ('getStringExtra','getData()','getText()','getUrl'):
            self.assertNotIn(forbidden,edge)

    def test_queue_edits_are_bounded_to_queue_copies(self):
        queue=(JAVA/'ReplayQueue.java').read_text()
        remove=queue[queue.index('static synchronized void remove'):queue.index('static synchronized void moveToFront')]
        self.assertIn('find(rows,id)',remove)
        self.assertIn('new File(dir,id+".html").delete()',remove)
        self.assertNotIn('getFilesDir',remove)
        self.assertIn('if(!id.matches("[a-f0-9-]{36}"))throw',queue[queue.index('private static int find'):])
        actions=(JAVA/'ConsoleActions.java').read_text()
        for name in ('removeQueued','moveQueuedToFront','clearQueue'):
            start=actions.index('static synchronized '+('int ' if name=='clearQueue' else 'void ')+name)
            self.assertIn('if(starting)throw',actions[start:start+250])

    def test_rows_prepared_ahead_never_publish_without_a_play_request(self):
        service=(JAVA/'PlaybackService.java').read_text()
        start=service.index('boolean wanted=');loop=service[start:service.index('if(phase.equals("complete")',start)]
        # Only an explicit replay or the user's play request for THIS row opens the game.
        self.assertIn('boolean wanted=!queueId.isEmpty()&&queueId.equals(ConsoleActions.playWhenReady());',loop)
        self.assertIn('(replayRequested||wanted)&&PlaybackHandoff.readyForForeground(',loop)
        # Queue edits cancel only before the scene and never after a foreground request.
        self.assertIn('PRE_SCENE.contains(phase)',loop)
        self.assertIn('!new File(status.getParentFile(),"foreground-request.json").exists()',loop)
        self.assertIn('"cancel_before_scene",true',loop)
        self.assertIn('"queued","preparing","calibrating","simulating","validating","ready_to_open"',service)
        handoff=(JAVA/'PlaybackHandoff.java').read_text()
        self.assertIn('if(PlaybackService.armedTask())return;',handoff)
        actions=(JAVA/'ConsoleActions.java').read_text()
        prepare=actions[actions.index('private static void prepareHead'):actions.index('static void autoPrepare(')]
        # Automatic preparation: game open, once per row per game process, never closes a terminal client.
        self.assertIn('pid=gamePid();if(pid<=0)return;',prepare)
        self.assertIn('if(before!=null&&before==pid)return;',prepare)
        self.assertIn('if(!user&&!reopened)return;',prepare)
        self.assertIn('StandaloneDoctor.root("pidof "+StandaloneDoctor.GAME,5)',actions)

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
