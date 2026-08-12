# -*- coding: ascii -*-
# Simulated depth sensor - the firmware's main source of non-determinism.
#
# Runs inside Renode as a Python peripheral. That interpreter is IronPython with
# Python 2 semantics, and it rejects non-ASCII source without a PEP 263 encoding
# declaration, so this file stays strictly ASCII. Keep it that way; the generator
# refuses to emit anything else.
#
# State persists between requests, so the PRNG stream is continuous across a run.
#
# The SEED line below is rewritten per run by tools/gen_run.py. It is the ONLY
# thing that varies between runs, and the replay path never sees it: replay reads
# recorded values from the trace, never from this peripheral.

SEED = 20260812

# Renode renamed the request attributes between 1.16.0 (isInit/isRead/value) and
# 1.16.1 (IsInit/IsRead/Value). Supporting both costs three lines and turns an
# obscure 'PythonRequest object has no attribute' crash into a non-event.
NEW_API = hasattr(request, 'IsInit')

if NEW_API:
    is_init = request.IsInit
    is_read = request.IsRead
else:
    is_init = request.isInit
    is_read = request.isRead

if is_init:
    rng_state = (SEED * 2654435761) & 0xFFFFFFFF
    if rng_state == 0:
        rng_state = 0x1234567  # xorshift is absorbing at zero
    baseline = 2048
    sample_count = 0

elif is_read:
    # xorshift32, chosen over anything fancier because the replay side has to be
    # able to state plainly that it does NOT reproduce this stream.
    rng_state ^= (rng_state << 13) & 0xFFFFFFFF
    rng_state ^= (rng_state >> 17)
    rng_state ^= (rng_state << 5) & 0xFFFFFFFF
    rng_state &= 0xFFFFFFFF

    # Slow drift plus per-sample noise, shaped like a 12-bit ADC reading.
    baseline += ((rng_state >> 16) % 3) - 1
    if baseline < 100:
        baseline = 100
    elif baseline > 3900:
        baseline = 3900

    value = baseline + ((rng_state % 129) - 64)
    if value < 0:
        value = 0
    elif value > 4095:
        value = 4095

    if NEW_API:
        request.Value = value
    else:
        request.value = value

    sample_count += 1
