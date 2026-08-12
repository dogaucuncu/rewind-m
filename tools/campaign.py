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

REPO = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_WORK = REPO / "build" / "campaign"

OUTCOME_OK = "ok"
OUTCOME_TORN = "torn"
OUTCOME_NO_TICKS = "no_ticks"
OUTCOME_NO_VERDICT = "no_verdict"
OUTCOME_CRASH = "renode_error"


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
    proc = subprocess.run(
        [renode, "--console", "--disable-xwt", "--plain",
         "-e", f"include @{resc.as_posix()}"],
        capture_output=True,
        text=True,
        timeout=300,
    )
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=int, default=1, help="first seed")
    parser.add_argument("--count", type=int, default=100, help="number of seeds")
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
    print(f"running {len(seeds)} seeds on {args.jobs} workers using {renode}")

    results: list[dict] = []
    started = time.monotonic()
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
    counts: dict[str, int] = {}
    for result in results:
        counts[result["outcome"]] = counts.get(result["outcome"], 0) + 1

    torn = counts.get(OUTCOME_TORN, 0)
    total = len(results)
    rate = torn / total if total else 0.0
    broken = total - counts.get(OUTCOME_OK, 0) - torn

    print()
    print(f"seeds          : {total}")
    print(f"clean runs     : {counts.get(OUTCOME_OK, 0)}")
    print(f"torn runs      : {torn}  ({rate * 100:.2f}%)")
    for outcome in (OUTCOME_NO_TICKS, OUTCOME_NO_VERDICT, OUTCOME_CRASH):
        if counts.get(outcome):
            print(f"{outcome:<15}: {counts[outcome]}")
    print(f"wall clock     : {time.monotonic() - started:.1f}s")

    failing = [r["seed"] for r in results if r["outcome"] == OUTCOME_TORN]
    if failing:
        shown = ", ".join(str(s) for s in failing[:20])
        suffix = " ..." if len(failing) > 20 else ""
        print(f"torn seeds     : {shown}{suffix}")

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(
                {
                    "total": total,
                    "counts": counts,
                    "torn_rate": rate,
                    "torn_seeds": failing,
                    "results": results,
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
