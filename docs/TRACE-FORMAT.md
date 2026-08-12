# Trace format

Fixed before either producer exists, so the in-firmware recorder (M3) and the emulator
oracle (M2) are writing to a specification rather than to each other.

## The logical model

A trace is an **ordered sequence of events**, each being one thing the firmware could not
have predicted:

| Kind | Meaning | Payload |
|---|---|---|
| `S` | read of the sensor data register (`0x50000000`) | 32-bit value returned |
| `J` | read of the timer jitter register (`0x50000004`) | 32-bit value returned |
| `I` | an interrupt was delivered | exception index — see note |

Order is part of the trace. Two traces are equal when their `(kind, payload)` sequences are
equal, element for element. Timestamps are *not* part of that comparison — see below.

**The oracle currently writes `0` as the interrupt payload.** Renode's interrupt hook takes a
line of Python, and none of the examples shipped with Renode reference a variable inside one,
so which names are in scope there is not something to guess at: an earlier attempt at
`exceptionIndex` raised after the hook had already created the output file, which produced an
empty trace and a confusing failure. The run now writes the hook's visible names to a
`.names` file alongside the trace, and the payload gets filled in once that has been read.
Only one interrupt source is enabled, so the count is meaningful in the meantime.

Everything else about a run — every branch, every store, the control output — follows from
the firmware image plus this sequence. That is the claim the whole project rests on, and
the differential check in M4 is what tests it.

## Why comparison ignores timestamps

The on-device recorder stamps events with the DWT cycle counter. The oracle, sitting outside
the CPU in the emulator, has no access to that counter without perturbing the machine it is
supposed to be observing neutrally.

So timestamps are recorded but excluded from equality. They exist to order events within one
trace and to measure recorder overhead, not to prove two traces match. Requiring them to
agree would be testing the emulator's timekeeping, not the recorder's completeness.

## Encodings

The same logical trace has two encodings. Both parse to the same list of events via
`tools/trace_format.py`, which is the only place either encoding is interpreted.

### Oracle encoding — text, one event per line

Written by Renode hooks (IronPython, ASCII-only, one-liners), so it is deliberately the
dumbest thing that works:

```
S 2043
S 2107
I 44
J 3735928559
```

This encoding is a debugging convenience. **No size claim is ever made about it** — the
oracle runs outside the target and has no byte budget.

### Device encoding — binary, specified here, implemented in M3

The recorder runs inside the firmware with a fixed cycle budget and a bounded ring buffer,
so its encoding has to be cheap to *write*, not cheap to read.

```
Header (8 bytes)
  0..3   magic   'R' 'W' 'M' '1'
  4      version (1)
  5      flags   bit0 set if the trace is truncated (see Gaps)
  6..7   reserved, zero

Record (variable length, little-endian)
  byte 0   kind, one of 'S' 'J' 'I' 'G'
  varint   cycles elapsed since the previous record (DWT CYCCNT delta)
  varint   payload
```

Varint is LEB128: seven bits per byte, high bit set while more bytes follow. Deltas rather
than absolute counts because consecutive events are close together, so most deltas fit in
one or two bytes.

Two compressions are specified and will be measured in M3 rather than assumed to help:

- a repeated payload identical to the previous event of the same kind is written as a
  zero-length payload
- reads whose value the firmware could have predicted are not recorded at all

The unit for reporting size is **bytes per thousand instructions**, the same unit TARDIS
reports, so the comparison can be made honestly in either direction.

### Gaps

If the ring buffer overflows, the recorder writes a `G` record whose payload is the number
of events it dropped, and sets the truncation flag in the header. Replay stops at a gap and
says so. It never continues past a hole and presents the result as faithful — a silently
wrong replay is the one outcome this project treats as unacceptable.

## What is not in the trace, and why

Interrupt *positions* are recorded as events in sequence, not as instruction counts. Under
Renode a run is a deterministic function of the image and the recorded input values, so the
positions could in principle be inferred rather than recorded. They are recorded anyway:
that inference is a property of the simulator, not of the technique, and on real silicon
interrupt arrival does not follow from the values read. See
[`LIMITS.md`](LIMITS.md#where-interrupts-land-is-implied-here-but-would-not-be-on-hardware).
