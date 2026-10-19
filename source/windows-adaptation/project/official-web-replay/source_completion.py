"""Pure completion gate for any bound source stream, not one 139-event fixture."""


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
