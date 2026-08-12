#!/usr/bin/env python3
"""Compare the in-firmware recorder's trace against the emulator's ground truth.

This is the check the project is built around. The recorder runs inside the
firmware under a cycle budget and a bounded buffer; the oracle watches the same
run from outside the CPU with none of those constraints. If the recorder drops,
reorders or mangles a single event, the two sequences stop matching and this
fails, naming the index where they first diverge.

    python tools/verify_recorder.py --count 5

Also reports what the recorder costs: cycles per event, trace bytes, and bytes
per thousand instructions - the same unit TARDIS reports, so the comparison can
be made in either direction.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import pathlib
import re
import sys

import gen_run
import renode_run
import trace_format
from campaign import find_renode

REPO = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_WORK = REPO / "build" / "recorder"

COST_RE = re.compile(r"^recorder cycles_per_event=(\d+) capacity=(\d+)$", re.MULTILINE)
TRACE_RE = re.compile(r"^trace bytes=(\d+) dropped=(\d+)$", re.MULTILINE)


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
    result: dict = {"seed": seed, "problems": []}
    try:
        proc = renode_run.run_script(renode, resc)
    except renode_run.RenodeTimeout as exc:
        # Reported for this seed and nothing else. Letting it escape would throw
        # away every other comparison in the batch, which is what used to happen.
        result["problems"].append(str(exc))
        return result

    if not uart_out.exists() or not oracle_out.exists():
        result["problems"].append("run produced no UART output or no oracle trace")
        result["stderr_tail"] = (proc.stderr or proc.stdout)[-400:]
        return result

    uart = uart_out.read_text(encoding="utf-8", errors="replace")

    try:
        data = trace_format.extract_hex_trace(uart)
        device, header = trace_format.parse_device_bytes(data)
    except trace_format.TraceError as exc:
        result["problems"].append(f"device trace: {exc}")
        return result

    oracle = trace_format.parse_oracle_text(oracle_out)

    cost = COST_RE.search(uart)
    stats = TRACE_RE.search(uart)

    # Instructions executed as of the last recorded event, written by a CPU hook.
    # That is the denominator the size figure wants: it covers the recorded run
    # and excludes the trace flush, which is not part of recording.
    instructions = None
    instr_tail = ""
    insn_file = oracle_out.with_suffix(".insn")
    if insn_file.exists():
        text = insn_file.read_text(encoding="ascii", errors="replace").strip()
        if text.isdigit():
            instructions = int(text)
        else:
            instr_tail = f"unparsable instruction count {text!r}"
    else:
        instr_tail = "no .insn file - the CPU hook did not run"

    result.update(
        device_events=len(device),
        oracle_events=len(oracle),
        bytes=len(data),
        truncated=header["truncated"],
        cycles_per_event=int(cost.group(1)) if cost else None,
        dropped=int(stats.group(2)) if stats else None,
        instructions=instructions,
    )
    if instructions is None:
        result["instr_tail"] = " ".join(instr_tail.split())[:200]
    if result["instructions"]:
        result["bytes_per_kinsn"] = round(
            len(data) * 1000.0 / result["instructions"], 4
        )

    if header["truncated"]:
        result["problems"].append(
            f"recorder dropped {result['dropped']} events - the buffer is too "
            "small for this run, so the traces cannot match"
        )
        return result

    divergence = trace_format.first_divergence(device, oracle)
    if divergence is not None:
        index, dev, orc = divergence
        result["problems"].append(
            f"traces diverge at event {index}: device={dev.key if dev else None} "
            f"oracle={orc.key if orc else None}"
        )
        # A divergence is usually one of two things: a genuinely missing event,
        # or the two sides encoding the same event differently. Printing the
        # shape of both traces distinguishes them without another round trip.
        result["shape"] = {
            "device_counts": trace_format.counts(device),
            "oracle_counts": trace_format.counts(oracle),
            "device_irq_payloads": sorted(
                {e.payload for e in device if e.kind == trace_format.KIND_IRQ}
            )[:5],
            "oracle_irq_payloads": sorted(
                {e.payload for e in oracle if e.kind == trace_format.KIND_IRQ}
            )[:5],
            "device_head": [e.key for e in device[:4]],
            "oracle_head": [e.key for e in oracle[:4]],
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--renode-dir", default=os.environ.get("RENODE_DIR"))
    parser.add_argument("--run-for", default="0.2")
    parser.add_argument("--work", type=pathlib.Path, default=DEFAULT_WORK)
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    args = parser.parse_args()

    renode = find_renode(args.renode_dir)
    status = 0
    seeds = list(range(args.start, args.start + args.count))

    # Each seed is an independent Renode process, so the only reason this was
    # serial was that nobody had needed more than five of them.
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(
            lambda seed: run_one(renode, seed, args.work, args.run_for), seeds
        ))

    for result in results:
        seed = result["seed"]
        if result["problems"]:
            status = 1
            print(f"seed {seed}: FAIL")
            for problem in result["problems"]:
                print(f"    {problem}")
            if "shape" in result:
                for key, value in result["shape"].items():
                    print(f"    {key}: {value}")
            if "stderr_tail" in result:
                print(f"    renode: {result['stderr_tail'].strip()[-300:]}")
        else:
            per_k = result.get("bytes_per_kinsn")
            print(
                f"seed {seed}: match  events={result['device_events']} "
                f"bytes={result['bytes']} "
                f"cycles/event={result['cycles_per_event']} "
                + (f"bytes/1k-insn={per_k}" if per_k else "instructions=unknown")
            )
            if per_k is None and result.get("instr_tail"):
                print(f"    console after marker: {result['instr_tail']}")

    if status:
        print(
            "\nThe recorder and the emulator do not agree about what happened. "
            "A replay built on this trace would be confidently wrong, which is "
            "worse than no replay.",
            file=sys.stderr,
        )
    return status


if __name__ == "__main__":
    sys.exit(main())
