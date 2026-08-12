# rewind-m

Deterministic record and replay for bare-metal Cortex-M firmware.

Record every non-deterministic input a firmware sees during a run — sensor samples,
interrupt arrivals — then reproduce that exact run later, event for event, from the trace
alone. The point is to take a fault that shows up in a small percentage of runs and make it
reproducible on demand.

No hardware required. Everything runs on [Renode](https://renode.io/); `make` and one
command gets you a running target.

> **Status: M4 — recording is verified, and the verification is itself tested.** There is a
> firmware with a real intermittent race, a recorder inside it, an emulator-side oracle that
> proves the recorder misses nothing, and evidence that both of those checks can fail when
> they should. Nothing is replayed yet; the replay engine is M5. Every number below was
> measured by a tool in this repository, and the ones that turned out worse than the prior
> art say so. See [Milestones](#milestones).

## Why this exists

Firmware bugs that appear once every few hundred runs are the expensive kind. They depend
on when an interrupt landed relative to the main loop, on a sensor value nobody logged, on
a race that vanishes the moment you attach a debugger. The usual response is to add print
statements and wait.

Record and replay attacks that directly: capture the non-determinism, then replay it as
many times as you like, in a debugger, with the fault reproducing every single time.

## Design

Non-determinism enters a bare-metal firmware through exactly two doors:

1. **Unpredictable peripheral register reads** — sensor data registers, status flags.
2. **When an interrupt is delivered** — where in the instruction stream an ISR preempts.

Everything else is a pure function of the binary and the initial state. So the recorder
only has to capture those two things.

```
RECORD
                    ┌──────────────────────────────────────────┐
   Renode Python    │  firmware (C, bare-metal)                │
   hooks inject ───►│    sensor read ──────────► recorder ──┐  │
   seeded           │    ISR entry ────────────► recorder ──┤  │
   non-determinism  │                                       ▼  │
                    │                         ring buffer (RAM)│
                    └───────────────────────────────────┬──────┘
                                                        │ UART flush
   ┌────────────────────────────────────────────┐       ▼
   │ ORACLE — Renode hooks independently record │   trace.bin
   │ the same events as ground truth            │       │
   └────────────────────┬───────────────────────┘       │
                        │                               │
                        └──────► DIFFERENTIAL ◄─────────┘
                                 VALIDATION
                     "did the recorder miss a single event?"

REPLAY — never sees the seed, reads only trace.bin
   same binary + recorded values fed back in
   + interrupts VERIFIED at recorded positions, not forced
   + the replay records its own trace, which must match the original
   + running out of recorded values is a failure, not a zero
```

### The product is in the firmware; the emulator only validates it

Recording from emulator hooks would have been easier, but the result would be an *emulator
tool* — it could never move to real silicon. The recorder is C code inside the firmware,
subject to the same constraints as any other on-device instrumentation: a fixed cycle
budget, a bounded ring buffer, a real bandwidth limit on getting the trace out.

Renode's hooks are used for something else: recording the same events independently, as
ground truth, so that CI can prove the in-firmware recorder did not miss anything. "What
did you test your recorder against?" has an answer.

Both sides exist now, and CI diffs them on every push:

```
20 seeds, 609 events each, matched exactly
trace 3635-3644 bytes · 94 cycles per event · 0.80 bytes per thousand instructions
```

A dropped, reordered or mangled event moves the sequences apart and the build fails, naming
the index where they first diverge. Interrupt payloads are excluded from the comparison —
Renode's hook reports the ARM exception class rather than the Cortex-M exception number, so
the two sides cannot mean the same thing by that field. Everything else is compared exactly,
order included.

TARDIS reports 0.5 bytes per thousand instructions; this recorder is at 0.80, with neither
of the two specified compressions implemented yet. Different workloads, so it is indicative
rather than a benchmark — but the direction is stated the way it came out.

A green check is worth nothing until it has been shown capable of going red, so both of
these are tested rather than trusted. Twenty-two unit tests prove the comparison rejects a
dropped event, a reordered pair, a changed payload, a short tail and an extra event. And the
recorder's overflow path — written in M3, never once executed — is now run deliberately in
CI with an undersized buffer, which must produce dropped events, a truncated flag, a gap
record carrying the firmware's own count, and a comparison that refuses to call it a match.

```bash
python tests/test_trace_format.py            # can the comparison say no?
python tools/verify_recorder.py --count 20   # diff recorder against oracle
python tools/verify_overflow.py              # make it overflow on purpose
python tools/verify_oracle.py --count 5      # oracle against the firmware's own counts
```

### Non-determinism is injected on purpose

Renode is deterministic by design. Recording inside a deterministic simulator and replaying
inside the same deterministic simulator proves nothing — of course it matches.

So every run injects **seeded** non-determinism: sensor noise, interrupt jitter, message
arrival timing. One rule makes the experiment honest, and CI enforces it:

> **The replay path never receives the seed.** It reads the trace and nothing else.

[`docs/LIMITS.md`](docs/LIMITS.md) lists which sources of non-determinism are captured and
which are not.

### Prior work

This is not a new idea, and the README will not pretend otherwise.
[TARDIS](https://engineering.purdue.edu/dcsl/publications/papers/2015/tardis_matt_ipsn15.pdf)
(Purdue, IPSN'15) did software-only system-level record and replay for wireless sensor
nodes; `rr` does it for Linux userspace; PANDA does whole-system replay on QEMU. What is
missing is a modern, reproducible implementation for bare-metal Cortex-M that anyone can
clone and run, and a recorder whose completeness is mechanically verified rather than
asserted. See [`docs/RELATED-WORK.md`](docs/RELATED-WORK.md).

## The fault, measured

The demo firmware is a depth-hold controller. Its TIM2 interrupt publishes each sensor
sample as two words — the value and its complement — without disabling interrupts. The
control loop reads the first word, computes its error term, then reads the second. An
interrupt landing in that window hands the loop one word from tick N and the other from
tick N+1.

`tools/campaign.py` runs the firmware under many seeds as independent headless Renode
processes and counts how many runs the fault appears in:

> **Being re-measured.** That rate was taken on a build without the recorder in it. Adding
> the recorder changed the timing enough that those seeds no longer hit the race — which is
> a real property of on-device recording, not an accident, and is written up in
> [`docs/LIMITS.md`](docs/LIMITS.md#the-recorder-changes-the-timing-it-records). The number
> returns once it has been measured on the build that ships.

How rare the fault is depends on how much work the controller does outside the window,
which is the `CONTROL_WORK` constant. The default is 4096, chosen from a sweep — see
[`docs/MEASUREMENTS.md`](docs/MEASUREMENTS.md) for the numbers and when each was taken.
That is the regime a replay tool is for: rare enough that running it again does not find
the bug, common enough to be real.

```bash
python tools/campaign.py --count 400                        # measure
python tools/campaign.py --sweep 0,64,512,4096 --count 40   # sweep the knob
```

A run that produces no verdict counts as a harness failure, not a pass — across every
campaign run so far, all of them produced one.

## Build and run

Requirements: `arm-none-eabi-gcc`, `make`, Python 3.11+, and Renode 1.16+.

```bash
make -C firmware                       # build the firmware
python tools/gen_run.py --seed 1234    # generate the Renode platform for a seed
scripts/test.sh                        # run the test suites under Renode
python tools/campaign.py --count 100   # measure the failure rate
```

On Windows use Git Bash for `make`; see [`docs/SETUP.md`](docs/SETUP.md) for the toolchain
notes, including which Renode package to install (the winget one is missing the CPU
translation libraries).

## Milestones

| | | Status |
|---|---|---|
| M0 | Toolchain, bare-metal target, DWT, seeded sensor peripheral, CI | done |
| M1 | Deliberate race + seeded injection + N-seed campaign | done — 7/400 |
| M2 | Oracle ground-truth recording + trace format | done |
| M3 | In-firmware recorder + overhead measurement | done |
| M4 | Differential validation as a CI gate | done |
| M5 | Replay engine + divergence detector | |
| M6 | Documentation, related work, demo | |

Scope for v1 is deliberately narrow: one board (STM32F4 Discovery), bare metal, sensor
reads and interrupt delivery. DMA, multi-core, RTOS scheduling and real-hardware validation
are explicitly out — see [`docs/LIMITS.md`](docs/LIMITS.md).

## License

MIT — see [LICENSE](LICENSE).
