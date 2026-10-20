"""Only an ordinary idle lobby may be replaced by a local source replay."""


def require_idle_lobby(state):
    expected=dict(controller_vtable_va='0x1bebd08',kind=0,state=9,domain_mode=1,
                  battle_present=False,pending_request=0,auxiliary_present=False)
    if any(state.get(key)!=value for key,value in expected.items()):
        raise ValueError('lobby required; foreign battle left unchanged before component load')


def battle_observation_ready(fields):
    # A Battle pointer can be published BEFORE Domain mode/resources/Scene
    # finish loading. Never call its finished()/health graph during that phase.
    return (len(fields)==48 and fields[5]==1 and fields[15]==fields[27] and fields[20]==1
            and fields[21]==9 and bool(fields[22]) and fields[24]==4 and bool(fields[26])
            and fields[28]==1 and fields[29]==0 and fields[30]>0)
