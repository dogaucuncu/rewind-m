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
| 2026-08-12 | runs that tore | 100% | 70% | 15% | 2.5% | **retracted** — see below |

The default of 4096 was chosen from the retracted sweep. The current 400-seed campaign puts
that point at 1.75%, close to the 2.5% the sweep reported, so the choice stands — but the
sweep itself needs re-running before its table is quoted as a measurement of this code.

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

## Reproducing

```bash
python tools/campaign.py --count 400
python tools/campaign.py --sweep 0,64,512,4096 --count 40
```

Or from the Actions tab: run the CI workflow manually, optionally ticking `sweep` and
setting `count`.
