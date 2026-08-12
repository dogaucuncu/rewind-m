# -*- coding: ascii -*-
# One of the two registers the firmware cannot predict. Instantiated twice, once
# per role, at:
#
#   0x50000000  ROLE = 'sensor'   depth reading, shaped like a 12-bit ADC sample
#   0x50000004  ROLE = 'jitter'   inter-tick delay jitter for the control timer
#
# Two peripherals rather than one with two offsets, deliberately. Renode's
# SetHookAfterPeripheralRead binds per peripheral and its documented, exercised
# variable is `value`; distinguishing registers inside one peripheral would mean
# relying on `offset` being present in the hook scope, which it is not. Splitting
# them makes the oracle's hooks unambiguous without depending on that.
#
# The streams are independent, so reading one does not shift the other. That
# matters for replay: each register's value sequence has to be reconstructible
# from the trace on its own.
#
# Constraints that shape this file: IronPython with Python 2 semantics; non-ASCII
# source is rejected without a PEP 263 declaration, so ASCII only (the generator
# enforces it); straight-line code, no function definitions, because the whole
# script is re-executed on every bus access.
#
# SEED and ROLE are rewritten per run by tools/gen_run.py. The seed is the ONLY
# thing that varies between runs, and the replay path never sees it: replay reads
# recorded values from the trace, never from this peripheral.

SEED = 20260812
ROLE = 'sensor'

# Renode renamed the request attributes between 1.16.0 (isInit/isRead/value) and
# 1.16.1 (IsInit/IsRead/Value). Supporting both costs a few lines and turns an
# obscure 'PythonRequest object has no attribute' crash - one that kills the
# whole Renode process mid-run - into a non-event.
NEW_API = hasattr(request, 'IsInit')

if NEW_API:
    is_init = request.IsInit
    is_read = request.IsRead
else:
    is_init = request.isInit
    is_read = request.isRead

if is_init:
    # Salt the seed per role so the two peripherals produce unrelated streams
    # from the same run seed.
    if ROLE == 'sensor':
        rng_state = (SEED * 2654435761) & 0xFFFFFFFF
    else:
        rng_state = ((SEED + 0x9E3779B9) * 2654435761) & 0xFFFFFFFF
    if rng_state == 0:
        rng_state = 0x1234567  # xorshift is absorbing at zero
    baseline = 2048
    reads = 0

elif is_read:
    # xorshift32
    rng_state ^= (rng_state << 13) & 0xFFFFFFFF
    rng_state ^= (rng_state >> 17)
    rng_state ^= (rng_state << 5) & 0xFFFFFFFF
    rng_state &= 0xFFFFFFFF

    if ROLE == 'sensor':
        # Slow drift plus per-sample noise. Consecutive samples stay close, so a
        # torn read of a two-word sample is usually survivable - which is exactly
        # why the resulting bug is intermittent rather than obvious.
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
    else:
        # The firmware masks this down to the range it wants; the peripheral
        # just supplies entropy.
        value = rng_state

    reads += 1

    if NEW_API:
        request.Value = value
    else:
        request.value = value
