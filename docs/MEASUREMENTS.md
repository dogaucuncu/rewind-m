# Measurements

Every number quoted anywhere in this repository is recorded here with what produced it, so
a reader can tell a measurement from an estimate — and can tell when one has been retracted.

All runs: Renode 1.16.1 linux-portable-dotnet, `ubuntu-latest` GitHub runner, 4 parallel
workers, 0.2 emulated seconds per seed, `tools/campaign.py`.

## Failure rate of the torn-read race

| Date | Build | Seeds | Torn | Rate | Torn seeds | Status |
|---|---|---|---|---|---|---|
| 2026-08-12 | with recorder | 400 | 13 | 3.25% | 6, 34, 70, 72, 144, 147, 177, 182, 187, 197, 239, 245, 285 | **current** |
| 2026-08-12 | no recorder | 400 | 7 | 1.75% | 55, 130, 145, 322, 329, 374, 380 | **superseded** - see below |
| 2026-08-12 | no recorder | 100 | 1 | 1.00% | 55 | superseded |
| 2026-08-12 | no recorder, stale peripheral | 400 | 5 | 1.25% | 39, 127, 269, 308, 397 | **retracted** - see below |

**The rate depends on whether the recorder is in the build, so the build is now part of the
measurement** - and not only which runs fail, but how many: 1.75% without the recorder,
3.25% with it. Adding instrumentation nearly doubled the failure rate rather than masking
it, because the extra work shifts where the interrupt falls relative to the window.

Every one of the seven seeds from the earlier row passes cleanly once the recorder is
present: reproduced faithfully from its trace, but as a clean run. The instrumentation costs
cycles, and a race that turns on where an interrupt lands relative to a few instructions is
sensitive to exactly that. See [`LIMITS.md`](LIMITS.md#the-recorder-changes-the-timing-it-records).

Rows marked superseded were correct for the build they were taken on. They are kept because
"this number changed when we added instrumentation" is the interesting part.

Zero runs in any campaign failed to produce a verdict.

## Cost of the work outside the window

`CONTROL_WORK` sets how much non-critical controller work sits outside the two shared-state
reads, which is what makes the race rare. Sweep, 40 seeds per point:

| Date | `CONTROL_WORK` | 0 | 64 | 512 | 4096 | Status |
|---|---|---|---|---|---|---|
| 2026-08-12 | runs that tore | 100% (40/40) | 72.5% (29/40) | 5% (2/40) | 0% (0/40) | **current** |
| 2026-08-12 | runs that tore | 100% | 70% | 15% | 2.5% | **retracted** — see below |

**40 seeds cannot resolve the 4096 point, and the table should not be read as if it could.**
At the rate the 400-seed campaign measured there, 1.75%, the chance of seeing zero failures
in 40 runs is `0.9825^40`, about 49% — a coin flip. The 0/40 above is that coin landing
tails, not a disagreement with 7/400.

What the sweep is good for is the shape of the curve: the fault goes from certain, to
frequent, to occasional, to rare as work moves outside the window. Pinning down the rare end
takes hundreds of seeds, which is why the per-point sweep and the headline campaign are
separate runs with different sizes.

The 512 point moved from 15% to 5% between the retracted and current sweeps. That is a real
change in behaviour, and it is one of the reasons the earlier numbers are retracted rather
than merely re-stated.

## Retraction: stale peripheral script in CI, 2026-08-12

CI unpacked Renode into `./renode`, the same directory as this project's own Renode
peripheral script. `actions/cache` covered that whole directory, so the archive saved on the
first green run contained `renode/sensor.py` as it stood at M0. The cache key never changed
and cache restore runs *after* checkout, so every subsequent run silently replaced the
checked-out script with the M0 version.

Nothing failed. The M0 script had no offset dispatch and answered every read with a sensor
sample, so the firmware's jitter register received a plausible value and the runs looked
healthy. The measurements were real measurements — of code that was not in the tree.

Fixed by installing Renode under `RUNNER_TEMP`, outside the workspace, so the collision
cannot recur, plus a CI step that fails the build if anything modifies tracked files after
checkout. The torn seed set changed completely after the fix (39 → 55 for the first
failure), which is the evidence that the peripheral behaviour really had been different.

Anything measured before that fix is retracted rather than deleted: knowing a number was
wrong, and why, is worth more than a clean table.

## Oracle agreement (M2)

Per push, five seeds, comparing the emulator's independent event count against the totals the
firmware reports for itself:

| Date | Seeds | Sensor reads | Jitter reads | Interrupts | Result |
|---|---|---|---|---|---|
| 2026-08-12 | 5 | 209 = 209 | 200 = 200 | 200 = 200 | agree exactly |

209 is 8 self-test samples, 1 priming read and one per tick. There is no recorder to diff
against yet — this is the strongest check available until M3, and it is what caught the
firmware reporting its counters while the timer was still running.

## Recorder against oracle (M3)

Per push, five seeds. The in-firmware recorder's trace is decoded and compared event by
event against the emulator's independent record of the same run:

| Date | Seeds | Events | Result | Trace bytes | Cycles/event | Bytes per 1k instructions |
|---|---|---|---|---|---|---|
| 2026-08-12 | 20 | 609 | match | 3635–3644 | 94 | 0.79–0.80 |
| 2026-08-12 | 5 | 609 | match | 3635–3642 | 94 | 0.79–0.80 |

609 events is 209 sensor reads, 200 jitter reads and 200 interrupts. Interrupt payloads are
excluded from the comparison for the reason given in
[`TRACE-FORMAT.md`](TRACE-FORMAT.md); everything else is compared exactly, including order.

**Against TARDIS: worse.** TARDIS reports 0.5 bytes per thousand instructions and about 5%
runtime overhead; this recorder is at 0.80 bytes per thousand instructions with neither of
the two specified compressions implemented. The workloads are not the same, so this is
indicative rather than a benchmark — but the direction is what it is, and closing the gap
would mean implementing the compressions and measuring again rather than arguing about it.

Cycles per event is measured in isolation before the run, driving the recorder in a loop, so
it includes that loop and is an upper bound.

## What the gates are worth (M4)

A green check means nothing until it has been shown capable of going red. Both of these
now have been:

| Gate | What proves it can fail |
|---|---|
| Trace comparison | 22 unit tests, including that it rejects a dropped event, a reordered pair, a changed payload, a short tail and an extra event — and that it still catches a missing interrupt despite ignoring interrupt payloads |
| Recorder overflow handling | A build with a 512-byte buffer, run in CI: events are dropped, the truncated flag is set, exactly one gap record carries the firmware's own count, and the comparison refuses to call the result a match |

The overflow path had been written in M3 and had never once executed. It works, but that
was not knowable until it was made to run.

## How many seeds a claim needs

A rate around 2% needs a few hundred seeds before it means anything. Rough guide, for
spotting a failure at all:

| True rate | Seeds for a ~95% chance of seeing at least one failure |
|---|---|
| 10% | 29 |
| 5% | 59 |
| 2% | 149 |
| 1% | 299 |

This is why the per-push CI campaign (100 seeds) does not gate on the failure rate: at 1.75%
it would report zero failures often enough to make the gate flake. It gates on every run
having produced a readable verdict instead.

## Reproducing

```bash
python tools/campaign.py --count 400
python tools/campaign.py --sweep 0,64,512,4096 --count 40
```

Or from the Actions tab: run the CI workflow manually, optionally ticking `sweep` and
setting `count`.
