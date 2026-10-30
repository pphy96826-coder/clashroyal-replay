"""Pure completion gate for any bound source stream, not one 139-event fixture."""


def source_failure(report):
    """Name the rejected queued command, not the next unsubmitted event."""
    if report.get('error')==123:
        floor=report.get('hp_floor_violation') or {}
        return '分支在 %.2f 秒越过 HTML 终局塔血下限：玩家%s，塔位%s，当前%s，至少%s；已剪枝'%(
            floor.get('native_tick',0)/20,floor.get('owner','?'),floor.get('tower_slot','?'),floor.get('actual_hp','?'),floor.get('expected_min','?'))
    if report.get('error')==125:return '技能身份或六塔观察无法验证；本候选不接受'
    if report.get('error')==112:
        if type(report.get('native_code')) is int and report['native_code']==0:
            return '第%d条技能在当前模拟分支中没有合法目标（适配器112）；该分支未完成，未跳过技能'%(report.get('event_index',-1)+1)
        return '第%d条技能的合法目标数为%d，技能目标未唯一确定（适配器112）'%(report.get('event_index',-1)+1,report.get('native_code',0))
    failed=next((row for row in report.get('dispatch',[]) if row.get('code',-1)>0),None)
    if failed:
        index=failed['index'];tick=failed['tick'];code=failed['code']
        detail=next((row for row in report.get('diagnostics',[]) if row.get('index')==index),{})
        message='第%d条指令（%.2f秒，卡牌ID %s）被原生引擎拒绝，返回码%d'%(index+1,tick/20,detail.get('card','未知'),code)
        if code==4 and failed.get('kind')==153:
            message+='：模拟已进入结算，不能继续出牌；这不是英雄技能目标冲突。模拟提前结算的原因仍需核对'
        return message
    return '源指令执行未完成：事件%d，tick %d，适配器%d，原生返回码%d'%(
        report.get('event_index',-1),report.get('tick',-1),report.get('error',-1),report.get('native_code',-1))


def source_completed(report, expected_count):
    if type(expected_count) is not int or expected_count < 1:
        raise ValueError('an explicit positive source event count is required')
    if report.get('error') != 0 or report.get('finished') != 1:
        return False
    if report.get('executed') != expected_count or report.get('native_accepted') != expected_count:
        return False
    commands, dispatch = report.get('commands', []), report.get('dispatch', [])
    if len(commands) != expected_count or len(dispatch) != expected_count:
        return False
    for index, (command, actual) in enumerate(zip(commands, dispatch)):
        body = command.get('c', {})
        tick = body.get('t')
        if type(tick) is not int or tick < 0 or body.get('t2') != tick:
            return False
        if actual != dict(index=index, kind=command.get('ct'), tick=tick, flags=3, code=0):
            return False
    return True
