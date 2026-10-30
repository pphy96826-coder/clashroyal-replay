"""Local message classification only: no emulator or replay simulation."""
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'official-web-replay'))
from failure_recovery import explanation,version_hint,VERSION_CHECK_HINT


def test_real_terminal_error_is_not_misclassified_by_negative_skill_phrase():
    text='第63条指令（189.90秒，卡牌ID 26000000）被原生引擎拒绝，返回码4：模拟已进入结算，不能继续出牌；这不是英雄技能目标冲突。模拟提前结算的原因仍需核对'
    result=explanation(RuntimeError(text))
    assert result.startswith('原生引擎已提前结算')
    assert VERSION_CHECK_HINT in result
    assert '技能所属单位无法唯一确定' not in result


def test_version_hint_only_for_known_mismatch_not_exact_or_unknown():
    for tier in ('same_towers','same_winner','different'):assert version_hint(tier)==VERSION_CHECK_HINT
    for tier in ('exact','unknown',None,''):assert version_hint(tier)==''


def test_real_ambiguity_and_elixir_messages_keep_their_specific_causes():
    assert explanation('ability target ambiguous').startswith('技能所属单位无法唯一确定')
    assert explanation('溢出圣水与网页不一致：蓝方').startswith('溢出圣水与网页不一致')

def test_zero_targets_are_distinguished_from_multiple_targets():
    result=explanation('第67条技能在当前模拟分支中没有合法目标（适配器112）')
    assert '没有合法目标' in result
    assert '多个候选' not in result


def test_normal_console_and_queued_ready_hint_share_the_same_version_message():
    java=(ROOT/'android-adaptation/app/src/local/royale/replay/android/ConsoleActions.java').read_text()
    runner=(ROOT/'android-adaptation/device/device_playback.py').read_text()
    assert VERSION_CHECK_HINT in java
    assert "context['version_check_hint']=version_hint(tier)" in runner
    assert "ready_message+=context.get('version_check_hint','')" in runner
