# -*- coding: ascii -*-
# The simulated world: everything the firmware cannot predict.
#
# Two 32-bit registers, both backed by seeded PRNG streams:
#
#   offset 0x0  SENSOR_DR   depth reading, shaped like a 12-bit ADC sample
#   offset 0x4  JITTER_DR   inter-tick delay jitter for the control timer
#
# The streams are independent, so reading one does not shift the other. That
# matters for replay: each register's value sequence has to be reconstructible
# from the trace on its own.
#
# Runs inside Renode as a Python peripheral. Constraints that shape this file:
#   - IronPython, Python 2 semantics
#   - non-ASCII source is rejected without a PEP 263 declaration, so ASCII only
#     (tools/gen_run.py refuses to emit anything else)
#   - straight-line code only, no function definitions: the whole script is
#     re-executed on every bus access and the scope model for defs is not
#     something this project needs to depend on
#
# The SEED line below is rewritten per run by tools/gen_run.py. It is the ONLY
# thing that varies between runs, and the replay path never sees it: replay reads
# recorded values from the trace, never from this peripheral.

SEED = 20260812

# Renode renamed the request attributes between 1.16.0 (isInit/isRead/value/
# offset) and 1.16.1 (IsInit/IsRead/Value/Offset). Supporting both costs a few
# lines and turns an obscure 'PythonRequest object has no attribute' crash - one
# that kills the whole Renode process mid-run - into a non-event.
NEW_API = hasattr(request, 'IsInit')

if NEW_API:
    is_init = request.IsInit
    is_read = request.IsRead
    offset = request.Offset
else:
    is_init = request.isInit
    is_read = request.isRead
    offset = request.offset

if is_init:
    sensor_state = (SEED * 2654435761) & 0xFFFFFFFF
    if sensor_state == 0:
        sensor_state = 0x1234567  # xorshift is absorbing at zero
    jitter_state = ((SEED + 0x9E3779B9) * 2654435761) & 0xFFFFFFFF
    if jitter_state == 0:
        jitter_state = 0x7654321
    baseline = 2048
    sensor_reads = 0
    jitter_reads = 0

elif is_read:
    if offset == 0x0:
        # xorshift32
        sensor_state ^= (sensor_state << 13) & 0xFFFFFFFF
        sensor_state ^= (sensor_state >> 17)
        sensor_state ^= (sensor_state << 5) & 0xFFFFFFFF
        sensor_state &= 0xFFFFFFFF

        # Slow drift plus per-sample noise. Consecutive samples stay close, so a
        # torn read of a two-word sample is usually survivable - which is exactly
        # why the resulting bug is intermittent rather than obvious.
        baseline += ((sensor_state >> 16) % 3) - 1
        if baseline < 100:
            baseline = 100
        elif baseline > 3900:
            baseline = 3900

        value = baseline + ((sensor_state % 129) - 64)
        if value < 0:
            value = 0
        elif value > 4095:
            value = 4095

        sensor_reads += 1

    else:
        # Timer jitter. The firmware masks this down to the range it wants; the
        # peripheral just supplies entropy.
        jitter_state ^= (jitter_state << 13) & 0xFFFFFFFF
        jitter_state ^= (jitter_state >> 17)
        jitter_state ^= (jitter_state << 5) & 0xFFFFFFFF
        jitter_state &= 0xFFFFFFFF
        value = jitter_state
        jitter_reads += 1

    if NEW_API:
        request.Value = value
    else:
        request.value = value
