#!/usr/bin/env python3
"""Prove the recorder's overflow path works, by making it overflow.

The recorder is supposed to handle a full buffer by counting what it drops,
flagging the trace truncated and emitting a gap record - and the tooling is
supposed to refuse to call such a trace a match. All of that was written and
none of it had ever executed. A failure path that has never run is not a
failure path; it is an intention.

This rebuilds the firmware with a deliberately undersized buffer, runs one seed,
and asserts the whole chain fires. It restores the normal build afterwards, so a
CI step that runs it cannot leave a crippled binary behind for later steps.

    python tools/verify_overflow.py

Exits non-zero if the overflow path does not behave as documented.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import subprocess
import sys

import campaign
import gen_run
import trace_format
from campaign import find_renode

REPO = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_WORK = REPO / "build" / "overflow"

TRACE_RE = re.compile(r"^trace bytes=(\d+) dropped=(\d+)$", re.MULTILINE)


def probe(renode: str, seed: int, work: pathlib.Path, run_for: str) -> list[str]:
    """Run one seed and return everything that did not behave as documented."""
    problems: list[str] = []
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
    proc = subprocess.run(
        [renode, "--console", "--disable-xwt", "--plain",
         "-e", f"include @{resc.as_posix()}"],
        capture_output=True, text=True, timeout=300,
    )
    if not uart_out.exists():
        return [f"no UART output: {(proc.stderr or proc.stdout)[-300:]}"]

    uart = uart_out.read_text(encoding="utf-8", errors="replace")
    stats = TRACE_RE.search(uart)
    if not stats:
        return ["firmware did not report trace bytes and dropped count"]
    reported_dropped = int(stats.group(2))

    if reported_dropped == 0:
        problems.append(
            "the buffer did not overflow - the test cannot prove anything about "
            "a path that was not taken; shrink TRACE_CAPACITY further"
        )

    try:
        data = trace_format.extract_hex_trace(uart)
        device, header = trace_format.parse_device_bytes(data)
    except trace_format.TraceError as exc:
        return problems + [f"truncated trace did not decode: {exc}"]

    if not header["truncated"]:
        problems.append("dropped events but the truncated flag is clear")

    gaps = [e for e in device if e.kind == trace_format.KIND_GAP]
    if len(gaps) != 1:
        problems.append(f"expected exactly one gap record, found {len(gaps)}")
    elif gaps[0].payload != reported_dropped:
        problems.append(
            f"gap record says {gaps[0].payload} events lost, firmware reported "
            f"{reported_dropped}"
        )

    oracle = trace_format.parse_oracle_text(oracle_out)
    if len(device) >= len(oracle):
        problems.append(
            f"device trace has {len(device)} events against the oracle's "
            f"{len(oracle)} - nothing appears to have been lost"
        )

    # The point of the flag: downstream tooling must refuse to treat this as a
    # match, even though the events it does contain are perfectly valid.
    if trace_format.first_divergence(device, oracle) is None:
        problems.append(
            "a truncated trace compared equal to the oracle - the comparison "
            "would bless an incomplete recording"
        )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--capacity", type=int, default=512,
                        help="TRACE_CAPACITY for the undersized build")
    parser.add_argument("--renode-dir", default=os.environ.get("RENODE_DIR"))
    parser.add_argument("--run-for", default="0.2")
    parser.add_argument("--work", type=pathlib.Path, default=DEFAULT_WORK)
    args = parser.parse_args()

    renode = find_renode(args.renode_dir)

    print(f"building with TRACE_CAPACITY={args.capacity}")
    campaign.rebuild_with(f"-DTRACE_CAPACITY={args.capacity}u")
    try:
        problems = probe(renode, args.seed, args.work, args.run_for)
    finally:
        # Restoring matters: leaving a crippled binary in build/ would make
        # every later step in the job measure the wrong firmware.
        print("restoring the default build")
        campaign.rebuild_with()

    if problems:
        print("\noverflow handling did not behave as documented:", file=sys.stderr)
        for problem in problems:
            print(f"    {problem}", file=sys.stderr)
        return 1

    print("overflow path OK: events dropped, trace flagged, gap recorded, "
          "comparison refused")
    return 0


if __name__ == "__main__":
    sys.exit(main())
