#!/usr/bin/env python3
"""Run the firmware under many seeds and measure how often the race fires.

This is the measurement the project's headline claim rests on, so it is a tool
rather than a paragraph: whatever rate it prints is the rate that gets written
down. Each seed is an independent Renode process driven by a generated script,
because Robot Framework's per-suite startup cost makes thousands of runs
impractical.

    python tools/campaign.py --count 300
    python tools/campaign.py --count 3000 --jobs 8 --report build/campaign.json
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

import gen_run
import renode_run

REPO = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_WORK = REPO / "build" / "campaign"

OUTCOME_OK = "ok"
OUTCOME_TORN = "torn"
OUTCOME_NO_TICKS = "no_ticks"
OUTCOME_NO_VERDICT = "no_verdict"
OUTCOME_CRASH = "renode_error"
OUTCOME_TIMEOUT = "timeout"


def find_renode(explicit: str | None) -> str:
    if explicit:
        candidate = pathlib.Path(explicit)
        if candidate.is_dir():
            for name in ("renode", "renode.exe", "Renode.exe"):
                if (candidate / name).exists():
                    return str(candidate / name)
            raise SystemExit(f"{candidate}: no renode executable inside")
        return str(candidate)

    found = shutil.which("renode")
    if found:
        return found
    raise SystemExit(
        "renode not found. Pass --renode-dir or put renode on PATH. "
        "See docs/SETUP.md."
    )


def classify(uart_text: str) -> tuple[str, dict]:
    """Turn one run's UART output into a verdict.

    Anything that is not an explicit verdict counts as a failure of the harness,
    not a pass. A run whose output we cannot read is not evidence of anything.
    """
    stats: dict[str, int] = {}
    for line in uart_text.splitlines():
        line = line.strip()
        if line.startswith("control "):
            for field in line.split()[1:]:
                if "=" in field:
                    key, _, raw = field.partition("=")
                    try:
                        stats[key] = int(raw, 0)
                    except ValueError:
                        pass
        elif line == "RUN OK":
            return OUTCOME_OK, stats
        elif line.startswith("RUN FAIL torn="):
            return OUTCOME_TORN, stats
        elif line == "RUN FAIL no_ticks":
            return OUTCOME_NO_TICKS, stats
    return OUTCOME_NO_VERDICT, stats


def run_one(renode: str, seed: int, work: pathlib.Path, run_for: str) -> dict:
    seed_dir = work / str(seed)
    seed_dir.mkdir(parents=True, exist_ok=True)

    uart_out = seed_dir / "uart.txt"
    # CreateFileBackend rotates to <name>.1 if the file already exists, which
    # would silently leave us parsing a stale run.
    if uart_out.exists():
        uart_out.unlink()

    resc = gen_run.generate_resc(seed, seed_dir, uart_out, run_for=run_for)

    started = time.monotonic()
    try:
        proc = renode_run.run_script(renode, resc)
    except renode_run.RenodeTimeout:
        # One wedged Renode process must not take the whole campaign with it.
        # Losing 400 runs to an unhandled exception on run 399 is a worse
        # outcome than recording this seed as a harness failure and moving on.
        return {
            "seed": seed,
            "outcome": OUTCOME_TIMEOUT,
            "returncode": None,
            "seconds": round(time.monotonic() - started, 2),
        }
    elapsed = time.monotonic() - started

    if not uart_out.exists():
        return {
            "seed": seed,
            "outcome": OUTCOME_CRASH,
            "returncode": proc.returncode,
            "stderr_tail": (proc.stderr or proc.stdout)[-400:],
            "seconds": round(elapsed, 2),
        }

    outcome, stats = classify(uart_out.read_text(encoding="utf-8", errors="replace"))
    return {
        "seed": seed,
        "outcome": outcome,
        "returncode": proc.returncode,
        "stats": stats,
        "seconds": round(elapsed, 2),
    }


BUILD_LOCK = REPO / "firmware" / "build" / ".rebuild.lock"


def rebuild_with(extra_cflags: str = "") -> None:
    """Rebuild the firmware from clean with extra compiler flags.

    Shared with the overflow test, which needs a deliberately undersized trace
    buffer. Always builds from clean: a stale object file compiled with
    different flags is exactly the kind of thing that makes a measurement quietly
    describe the wrong binary.

    Held under an exclusive lock because every tool loads the same
    firmware/build/rewind-m.elf by path. Without it, running the overflow test
    while a campaign is in flight leaves the campaign measuring a 512-byte-buffer
    binary and reporting numbers that look entirely plausible - the same shape as
    the stale-peripheral incident in docs/MEASUREMENTS.md.
    """
    BUILD_LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock = os.open(BUILD_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SystemExit(
            f"{BUILD_LOCK} exists: another tool is rebuilding the firmware, and "
            "sharing one build directory would make both measure the wrong "
            "binary. Wait for it, or delete the lock if nothing is running."
        ) from None
    try:
        os.write(lock, (extra_cflags or "defaults").encode("ascii"))
        os.close(lock)
        _rebuild_locked(extra_cflags)
    finally:
        BUILD_LOCK.unlink(missing_ok=True)


def _rebuild_locked(extra_cflags: str) -> None:
    subprocess.run(
        ["make", "-C", str(REPO / "firmware"), "clean"],
        check=True, capture_output=True, text=True,
    )
    args = ["make", "-C", str(REPO / "firmware")]
    if extra_cflags:
        args.append(f"EXTRA_CFLAGS={extra_cflags}")
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"build failed for {extra_cflags or 'defaults'}:\n{proc.stderr}")


def rebuild(control_work: int) -> None:
    """Rebuild the firmware with a given CONTROL_WORK, for sweeps."""
    rebuild_with(f"-DCONTROL_WORK={control_work}")


def run_seeds(renode: str, seeds: list[int], args) -> list[dict]:
    results: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {
            pool.submit(run_one, renode, seed, args.work, args.run_for): seed
            for seed in seeds
        }
        for done, future in enumerate(concurrent.futures.as_completed(futures), 1):
            results.append(future.result())
            if done % 25 == 0 or done == len(seeds):
                print(f"  {done}/{len(seeds)}", flush=True)
    results.sort(key=lambda r: r["seed"])
    return results


def summarise(results: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for result in results:
        counts[result["outcome"]] = counts.get(result["outcome"], 0) + 1
    total = len(results)
    torn = counts.get(OUTCOME_TORN, 0)
    return {
        "total": total,
        "counts": counts,
        "torn": torn,
        "torn_rate": torn / total if total else 0.0,
        "broken": total - counts.get(OUTCOME_OK, 0) - torn,
        "torn_seeds": [r["seed"] for r in results if r["outcome"] == OUTCOME_TORN],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=int, default=1, help="first seed")
    parser.add_argument("--count", type=int, default=100, help="number of seeds")
    parser.add_argument(
        "--sweep",
        help="comma-separated CONTROL_WORK values; rebuilds and measures each",
    )
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--renode-dir", default=os.environ.get("RENODE_DIR"))
    parser.add_argument("--run-for", default="0.5", help="emulated seconds per run")
    parser.add_argument("--work", type=pathlib.Path, default=DEFAULT_WORK)
    parser.add_argument("--report", type=pathlib.Path)
    parser.add_argument(
        "--max-failure-rate",
        type=float,
        help="exit non-zero if the torn rate exceeds this (CI regression gate)",
    )
    parser.add_argument(
        "--expect-failures",
        action="store_true",
        help="exit non-zero if NO run tore; the race is supposed to be reachable",
    )
    args = parser.parse_args()

    renode = find_renode(args.renode_dir)
    seeds = list(range(args.start, args.start + args.count))
    started = time.monotonic()

    sweep_values = None
    if args.sweep:
        sweep_values = [int(v) for v in args.sweep.split(",") if v.strip()]

    passes: list[dict] = []
    if sweep_values:
        print(f"sweeping CONTROL_WORK over {sweep_values}, {len(seeds)} seeds each")
        for value in sweep_values:
            print(f"\n-- CONTROL_WORK={value}")
            rebuild(value)
            results = run_seeds(renode, seeds, args)
            summary = summarise(results)
            summary["control_work"] = value
            summary["results"] = results
            passes.append(summary)
            print(
                f"   torn {summary['torn']}/{summary['total']}"
                f"  ({summary['torn_rate'] * 100:.2f}%)"
                f"  broken {summary['broken']}"
            )
    else:
        print(f"running {len(seeds)} seeds on {args.jobs} workers using {renode}")
        results = run_seeds(renode, seeds, args)
        summary = summarise(results)
        summary["results"] = results
        passes.append(summary)

    final = passes[-1]
    counts = final["counts"]
    total = final["total"]
    torn = final["torn"]
    rate = final["torn_rate"]
    broken = final["broken"]
    failing = final["torn_seeds"]

    print()
    if sweep_values:
        print(f"{'CONTROL_WORK':>13} {'torn':>6} {'seeds':>6} {'rate':>8} {'broken':>7}")
        for summary in passes:
            print(
                f"{summary['control_work']:>13} {summary['torn']:>6} "
                f"{summary['total']:>6} {summary['torn_rate'] * 100:>7.2f}% "
                f"{summary['broken']:>7}"
            )
        print()
    print(f"seeds          : {total}")
    print(f"clean runs     : {counts.get(OUTCOME_OK, 0)}")
    print(f"torn runs      : {torn}  ({rate * 100:.2f}%)")
    for outcome in (OUTCOME_NO_TICKS, OUTCOME_NO_VERDICT, OUTCOME_CRASH,
                    OUTCOME_TIMEOUT):
        if counts.get(outcome):
            print(f"{outcome:<15}: {counts[outcome]}")
    print(f"wall clock     : {time.monotonic() - started:.1f}s")

    if failing:
        shown = ", ".join(str(s) for s in failing[:20])
        suffix = " ..." if len(failing) > 20 else ""
        print(f"torn seeds     : {shown}{suffix}")

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(
                {
                    "sweep": sweep_values,
                    "passes": [
                        {k: v for k, v in p.items() if k != "results"} for p in passes
                    ],
                    "total": total,
                    "counts": counts,
                    "torn_rate": rate,
                    "torn_seeds": failing,
                    "results": final["results"],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"report         : {args.report}")

    status = 0
    if broken:
        print(f"\nFAIL: {broken} run(s) produced no usable verdict", file=sys.stderr)
        status = 1
    if args.expect_failures and torn == 0:
        print(
            "\nFAIL: no run tore. The race is supposed to be reachable; if this "
            "is intentional, the campaign parameters need revisiting.",
            file=sys.stderr,
        )
        status = 1
    if args.max_failure_rate is not None and rate > args.max_failure_rate:
        print(
            f"\nFAIL: torn rate {rate:.4f} exceeds {args.max_failure_rate:.4f}",
            file=sys.stderr,
        )
        status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
