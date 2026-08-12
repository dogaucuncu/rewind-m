# -*- coding: ascii -*-
# Replay peripheral: serves values recorded in a previous run, in order.
#
# There is deliberately no seed in this file and no way to compute one. The only
# thing it knows is a list of values taken from a trace. That is what makes the
# reproduction claim mean anything: if the seed were reachable from here, replay
# would be re-running the experiment rather than reproducing it from evidence.
#
# tools/replay.py checks that no SEED line exists here before it will run.
#
# Constraints, same as the recording peripheral: IronPython with Python 2
# semantics, ASCII only, and straight-line code - the whole script is
# re-executed on every bus access.
#
# VALUES and EXHAUSTED_LOG are rewritten per replay by tools/gen_run.py.

VALUES = []
EXHAUSTED_LOG = ''

NEW_API = hasattr(request, 'IsInit')

if NEW_API:
    is_init = request.IsInit
    is_read = request.IsRead
else:
    is_init = request.isInit
    is_read = request.isRead

if is_init:
    index = 0
    overruns = 0

elif is_read:
    if index < len(VALUES):
        value = VALUES[index]
        index += 1
    else:
        # The firmware asked for more input than the trace holds. Under replay
        # that means the run has left the path the trace describes, so it is
        # recorded rather than papered over with a plausible-looking zero.
        overruns += 1
        value = 0
        with open(EXHAUSTED_LOG, 'a') as f:
            f.write('overrun after %d values' % len(VALUES) + chr(10))

    if NEW_API:
        request.Value = value
    else:
        request.value = value
