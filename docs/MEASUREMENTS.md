# Measurements

Every number quoted anywhere in this repository is recorded here with what produced it, so
a reader can tell a measurement from an estimate — and can tell when one has been retracted.

All runs: Renode 1.16.1 linux-portable-dotnet, `ubuntu-latest` GitHub runner, 4 parallel
workers, 0.2 emulated seconds per seed, `tools/campaign.py`.

## Failure rate of the torn-read race

| Date | Seeds | Torn | Rate | Torn seeds | Status |
|---|---|---|---|---|---|
| 2026-08-12 | 400 | 7 | 1.75% | 55, 130, 145, 322, 329, 374, 380 | **current** |
| 2026-08-12 | 100 | 1 | 1.00% | 55 | current, per-push gate |
| 2026-08-12 | 400 | 5 | 1.25% | 39, 127, 269, 308, 397 | **retracted** — see below |

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
