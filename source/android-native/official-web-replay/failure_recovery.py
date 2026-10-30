"""User-facing failure classification; never infer a dual-hero cause from count."""
import re

VERSION_CHECK_HINT='请先检查游戏客户端版本及回放日期，确认是否跨越平衡性调整；版本或战斗参数变化可能造成差异，不能仅据此归因于随机种子或技能目标。'


def version_hint(tier):
    return VERSION_CHECK_HINT if tier in ('same_towers','same_winner','different') else ''

def explanation(error):
    text = str(error)
    lower = text.lower()
    if '溢出圣水与网页不一致' in text:
        # The elixir gate's own message names both values and the implied ability cost.
        return text.split('）；未放行')[0] + '）。终局溢出圣水必须与网页一致才放行。' if '）；未放行' in text else text
    if any(word in lower for word in ('native expression', 'without a running target',
                                     "interpreter doesn't handle", 'jit compiled function')):
        return '本机调试器无法执行原生函数调用；不是手牌或技能目标错误。可能涉及调试上下文或虚拟机执行能力，具体原因请查看诊断记录。'
    # A dispatch error may explicitly say "这不是英雄技能目标冲突".
    # Classify the actual terminal refusal before matching those quoted words.
    if any(word in lower for word in ('code=4', 'native4', '返回码4', '提前结算', '已进入结算', 'already terminal', '已结算')):
        return '原生引擎已提前结算，后续指令被拒绝。'+VERSION_CHECK_HINT+'其他可能原因包括时序或初始化差异，目前不认定唯一原因。'
    if '没有合法目标' in lower or '合法目标数为0' in lower:
        return '该模拟分支在技能时刻没有合法目标；可能是此前交互、目标存活状态或版本参数产生偏差。未跳过技能；请核对种子搜索记录及客户端版本。'
    if any(word in lower for word in ('ambiguous', 'ability target', '技能目标')):
        return '技能所属单位无法唯一确定；可能存在多个候选单位，未猜测目标或跳过技能。'
    if ('card-unavailable' in lower or '牌序' in lower
            or re.search(r'\b(?:hand|deal)[-_ ](?:mismatch|unavailable|cycle|calibration)\b',lower)):
        return '实际手牌或卡牌循环与原始指令不一致；未跳过该条出牌。'
    if any(word in lower for word in ('场景未就绪', 'scene still loading', 'loading', 'driver')):
        return '原生画面加载或播放驱动未通过检查；不是仅凭英雄数量作出的判断。'
    return '回放未通过完整校验。具体错误已保留；可能涉及客户端战斗参数版本、技能目标或资源加载，不能仅归因于双英雄。'
