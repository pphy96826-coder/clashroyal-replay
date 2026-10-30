"""Which debugger stops may be handed back to the game while our task runs.

The game's own runtime raises signals while it runs (ART implicit null and
suspend checks, VM hook layers). Without a debugger the game handles them
itself, so a signal stop on a thread outside our component is resumed with the
signal still delivered (never suppressed). A stop inside our component, a
breakpoint/trap, SIGKILL or any non-signal stop is not foreign and fails closed.
"""

NOT_FOREIGN_SIGNALS = (5, 9)  # SIGTRAP, SIGKILL


def stop_reasons(lldb, process):
    rows = []
    for thread in process:
        reason = thread.GetStopReason()
        if reason in (lldb.eStopReasonNone, lldb.eStopReasonInvalid):
            continue
        rows.append(dict(tid=thread.GetThreadID(), reason=reason,
                         signal=thread.GetStopReasonDataAtIndex(0) if reason == lldb.eStopReasonSignal else None,
                         pc=hex(thread.GetFrameAtIndex(0).GetPC()), description=thread.GetStopDescription(200)))
    return rows


def foreign_signal(lldb, process, regions):
    """The stop rows when every stopped thread holds a game-runtime signal outside
    our component; None otherwise."""
    rows = stop_reasons(lldb, process)
    if not rows or any(r['reason'] != lldb.eStopReasonSignal or r['signal'] in NOT_FOREIGN_SIGNALS for r in rows):
        return None
    if any(low <= int(r['pc'], 16) < high for r in rows for low, high in regions):
        return None
    return rows
