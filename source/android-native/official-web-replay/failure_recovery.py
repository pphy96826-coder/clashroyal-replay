"""User-facing failure classification; never infer a dual-hero cause from count."""
import re

def explanation(error):
    text = str(error)
    lower = text.lower()
    if '溢出圣水与网页不一致' in text:
        # The elixir gate's own message names both values and the implied ability cost.
        return text.split('）；未放行')[0] + '）。终局溢出圣水必须与网页一致才放行。' if '）；未放行' in text else text
    if any(word in lower for word in ('native expression', 'without a running target',
                                     "interpreter doesn't handle", 'jit compiled function')):
        return '本机调试器无法执行原生函数调用；不是手牌或技能目标错误。可能涉及调试上下文或虚拟机执行能力，具体原因请查看诊断记录。'
    if any(word in lower for word in ('ambiguous', 'ability target', '技能目标')):
        return '技能所属单位无法唯一确定；可能存在多个候选单位，未猜测目标或跳过技能。'
    if any(word in lower for word in ('code=4', 'native4', '提前结算', 'already terminal', '已结算')):
        return '原生引擎已提前结算，后续指令被拒绝；可能与录像时期的平衡参数、时序或初始化差异有关，尚不能确定唯一原因。'
    if ('card-unavailable' in lower or '牌序' in lower
            or re.search(r'\b(?:hand|deal)[-_ ](?:mismatch|unavailable|cycle|calibration)\b',lower)):
        return '实际手牌或卡牌循环与原始指令不一致；未跳过该条出牌。'
    if any(word in lower for word in ('场景未就绪', 'scene still loading', 'loading', 'driver')):
        return '原生画面加载或播放驱动未通过检查；不是仅凭英雄数量作出的判断。'
    return '回放未通过完整校验。具体错误已保留；可能涉及客户端战斗参数版本、技能目标或资源加载，不能仅归因于双英雄。'
