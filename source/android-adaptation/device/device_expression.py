"""Evaluate once in an explicitly bound, stopped native frame.

No fallback thread, expression retry, JIT override or security-policy change.
The caller has already verified the target generation and function pins.
"""


def rejected_before_load(receipt):
    """Narrow LLDB parse-only refusal, not a generic failed native call.

    This message is emitted before execution by the IR interpreter when LLDB
    chose its never-run policy. The caller must ALSO check the same live
    generation, no component mappings, no tracer and a strict idle lobby.
    """
    errors=receipt.get('errors')
    return (receipt.get('initialization_only') is True
            and receipt.get('detached') is True
            and receipt.get('publication') is None
            and 'publication' in receipt
            and 'owned_loader_handle' not in receipt
            and 'fields' not in receipt
            and isinstance(errors,list) and len(errors)==1
            and "Can't evaluate the expression without a running target due to:" in str(errors[0])
            and "Interpreter doesn't handle one of the expression's opcodes" in str(errors[0]))


def evaluate(lldb, target, process, pid, expression, *, stop_others=True, evidence=None):
    info = evidence if evidence is not None else {}
    info.clear()
    info.update(phase='binding_frame', native_call_completed=False)
    try:
        if not process.IsValid() or process.GetProcessID() != pid:
            raise RuntimeError('native expression process identity differs')
        info.update(process_state=process.GetState(), target_triple=target.GetTriple())
        if process.GetState() != lldb.eStateStopped:
            raise RuntimeError('native expression requires a stopped process; not resumed automatically')
        bound = target.GetProcess()
        if not bound.IsValid() or bound.GetProcessID() != pid:
            raise RuntimeError('native expression target belongs to another process')
        if target.GetAddressByteSize() != 8:
            raise RuntimeError('native expression requires the pinned 64-bit target')
        thread = process.GetThreadByID(pid)
        if not thread.IsValid() or thread.GetThreadID() != pid:
            raise RuntimeError('bound main thread absent; no substitute thread selected')
        if not process.SetSelectedThread(thread):
            raise RuntimeError('bound main thread could not be selected')
        frame = thread.GetFrameAtIndex(0)
        if not frame.IsValid() or frame.GetThread().GetThreadID() != pid:
            raise RuntimeError('bound main-thread frame absent; target-only evaluation refused')
        info.update(thread_id=pid, frame_pc=hex(frame.GetPC()), phase='evaluating_bound_frame')
        options = lldb.SBExpressionOptions()
        options.SetLanguage(lldb.eLanguageTypeC)
        options.SetAllowJIT(True)
        options.SetTimeoutInMicroSeconds(5000000)
        options.SetIgnoreBreakpoints(True)
        options.SetUnwindOnError(True)
        options.SetStopOthers(stop_others)
        # SBTarget evaluation reconstructs an implicit execution context. Bind
        # directly to the verified frame instead, including in nested Android.
        value = frame.EvaluateExpression(expression, options)
        if not value.GetError().Success():
            raise RuntimeError('native expression failed: '+str(value.GetError()))
        info.update(phase='complete', native_call_completed=True)
        return value.GetValueAsUnsigned()
    except Exception as error:
        info['error'] = str(error)[:2000]
        info['execution_unavailable'] = 'without a running target' in str(error).lower()
        raise
