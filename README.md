# rewind-m

Deterministic record and replay for bare-metal Cortex-M firmware.

Record every non-deterministic input a firmware sees during a run — sensor samples,
interrupt arrivals — then reproduce that exact run later, bit for bit, from the trace
alone. The point is to take a fault that happens in 7 runs out of 3000 and make it
reproducible on demand.

No hardware required. Everything runs on [Renode](https://renode.io/); `make` and one
command gets you a running target.

> **Status: M1 — the fault exists and is measured.** There is a firmware with a real
> intermittent race, and a campaign runner that measures how often it fires. The recorder,
> the replay engine and the differential validation are M3–M5, so nothing is being replayed
> yet. Every number below was measured by a tool in this repository; none of them are
> estimates. See [Milestones](#milestones).

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
   same binary + recorded values forced in
   + interrupts forced at recorded positions
   + DIVERGENCE DETECTOR: if event N does not match, fail loudly
```

### The product is in the firmware; the emulator only validates it

Recording from emulator hooks would have been easier, but the result would be an *emulator
tool* — it could never move to real silicon. The recorder is C code inside the firmware,
subject to the same constraints as any other on-device instrumentation: a fixed cycle
budget, a bounded ring buffer, a real bandwidth limit on getting the trace out.

Renode's hooks are used for something else: recording the same events independently, as
ground truth, so that CI can prove the in-firmware recorder did not miss anything. "What
did you test your recorder against?" has an answer.

That oracle exists now. It records every sensor read, jitter read and interrupt delivery
from outside the CPU, in the format fixed by [`docs/TRACE-FORMAT.md`](docs/TRACE-FORMAT.md)
before either producer was written. Until the recorder lands there is nothing to diff
against, so CI checks the next best thing on every push: the firmware counts the
non-deterministic inputs it consumed and prints the totals, and those must match the
oracle's independent count exactly.

```bash
python tools/verify_oracle.py --count 5
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

```
400 seeds, 393 clean, 7 torn  (1.75%)
torn seeds: 55, 130, 145, 322, 329, 374, 380
```

Those seven seeds are what M5 will have to reproduce from a trace alone.

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
| M3 | In-firmware recorder + overhead measurement | |
| M4 | Differential validation as a CI gate | |
| M5 | Replay engine + divergence detector | |
| M6 | Documentation, related work, demo | |

Scope for v1 is deliberately narrow: one board (STM32F4 Discovery), bare metal, sensor
reads and interrupt delivery. DMA, multi-core, RTOS scheduling and real-hardware validation
are explicitly out — see [`docs/LIMITS.md`](docs/LIMITS.md).

## License

MIT — see [LICENSE](LICENSE).
