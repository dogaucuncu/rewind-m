#!/usr/bin/env python3
"""Cross-check the emulator's ground truth against what the firmware counted.

M2 does not have the in-firmware recorder yet, so there is no trace to compare
against a trace. There is something better than nothing, though: the firmware
counts the non-deterministic reads it consumed and prints the totals, and the
oracle counts the same events independently from outside the CPU. If those two
numbers disagree, one of them is wrong, and finding that out now is cheaper than
finding it out in M4 with a recorder in the middle to blame.

    python tools/verify_oracle.py --count 5

Exits non-zero on any disagreement.
"""

from __future__ import annotations

import argparse
import collections
import os
import pathlib
import re
import sys

import gen_run
import renode_run
import trace_format
from campaign import find_renode

REPO = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_WORK = REPO / "build" / "oracle"

READS_RE = re.compile(r"^reads sensor=(\d+) jitter=(\d+)$", re.MULTILINE)
CONTROL_RE = re.compile(r"^control ticks=(\d+) ", re.MULTILINE)


def run_one(renode: str, seed: int, work: pathlib.Path, run_for: str) -> dict:
    seed_dir = work / str(seed)
    seed_dir.mkdir(parents=True, exist_ok=True)

    uart_out = seed_dir / "uart.txt"
    oracle_out = seed_dir / "oracle.trace"
    for stale in (uart_out, oracle_out):
        if stale.exists():
            stale.unlink()

    resc = gen_run.generate_resc(
        seed, seed_dir, uart_out, run_for=run_for, oracle_out=oracle_out
    )
    try:
        proc = renode_run.run_script(renode, resc)
    except renode_run.RenodeTimeout as exc:
        return {"seed": seed, "returncode": None, "problems": [str(exc)]}

    result: dict = {"seed": seed, "returncode": proc.returncode, "problems": []}

    if not uart_out.exists():
        result["problems"].append("no UART output")
        result["stderr_tail"] = (proc.stderr or proc.stdout)[-400:]
        return result
    if not oracle_out.exists():
        result["problems"].append(
            "no oracle trace - the hooks did not run; check the monitor log for "
            "a tokenizer or NameError from the hook body"
        )
        result["stderr_tail"] = (proc.stderr or proc.stdout)[-400:]
        return result

    uart = uart_out.read_text(encoding="utf-8", errors="replace")
    reads = READS_RE.search(uart)
    control = CONTROL_RE.search(uart)
    if not reads or not control:
        result["problems"].append("firmware did not report its counts")
        return result

    fw_sensor, fw_jitter = int(reads.group(1)), int(reads.group(2))
    ticks = int(control.group(1))

    # Informational only: what the interrupt hook can actually see. Never fails
    # the run - it exists so the next enrichment of the trace does not have to
    # be guessed at across a CI round trip.
    names_file = oracle_out.with_suffix(".names")
    if names_file.exists():
        result["hook_names"] = names_file.read_text(
            encoding="ascii", errors="replace"
        ).strip()

    events = trace_format.parse_oracle_text(oracle_out)
    tally = trace_format.counts(events)
    irq_indices = collections.Counter(
        e.payload for e in events if e.kind == trace_format.KIND_IRQ
    )

    result.update(
        firmware={"sensor": fw_sensor, "jitter": fw_jitter, "ticks": ticks},
        oracle=tally,
        irq_indices=dict(irq_indices),
        events=len(events),
    )

    if tally[trace_format.KIND_SENSOR] != fw_sensor:
        result["problems"].append(
            f"sensor reads: firmware {fw_sensor}, oracle "
            f"{tally[trace_format.KIND_SENSOR]}"
        )
    if tally[trace_format.KIND_JITTER] != fw_jitter:
        result["problems"].append(
            f"jitter reads: firmware {fw_jitter}, oracle "
            f"{tally[trace_format.KIND_JITTER]}"
        )
    # One interrupt source is enabled and the firmware disables it before
    # reporting, so the counts should match exactly. If they do not, the
    # histogram of exception indices says whether something else fired.
    if tally[trace_format.KIND_IRQ] != ticks:
        result["problems"].append(
            f"interrupts: oracle saw {tally[trace_format.KIND_IRQ]}, "
            f"firmware counted {ticks} ticks; indices {dict(irq_indices)}"
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--renode-dir", default=os.environ.get("RENODE_DIR"))
    parser.add_argument("--run-for", default="0.2")
    parser.add_argument("--work", type=pathlib.Path, default=DEFAULT_WORK)
    args = parser.parse_args()

    renode = find_renode(args.renode_dir)
    status = 0

    for seed in range(args.start, args.start + args.count):
        result = run_one(renode, seed, args.work, args.run_for)
        if result["problems"]:
            status = 1
            print(f"seed {seed}: FAIL")
            for problem in result["problems"]:
                print(f"    {problem}")
            if "stderr_tail" in result:
                print(f"    renode: {result['stderr_tail'].strip()[-300:]}")
        else:
            fw = result["firmware"]
            print(
                f"seed {seed}: ok  sensor={fw['sensor']} jitter={fw['jitter']} "
                f"ticks={fw['ticks']} irq={result['oracle']['I']}"
            )
        if "hook_names" in result:
            print(f"    interrupt hook scope: {result['hook_names']}")

    if status:
        print(
            "\nThe firmware and the emulator disagree about what happened. "
            "One of the two counts is wrong; neither can be trusted until it is "
            "resolved.",
            file=sys.stderr,
        )
    return status


if __name__ == "__main__":
    sys.exit(main())
