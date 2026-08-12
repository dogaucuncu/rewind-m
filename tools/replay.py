#!/usr/bin/env python3
"""Reproduce a recorded run from its trace, and nothing else.

Two phases. First the run is recorded normally, with a seed. Then the seed is
put away and the firmware is run again against peripherals that serve the values
the trace holds - the replay side is handed a list of numbers and has no way to
reach the seed that produced them. `gen_run.render_replay` refuses to build a
replay peripheral that contains one.

Reproduction is judged three ways, all of which must hold:

  * the trace the replay run records matches the original event for event,
    payloads included - both come from the same recorder, so this is stricter
    than the recorder-vs-oracle comparison
  * the firmware reaches the same verdict, with the same torn count and the
    same control checksum
  * no peripheral ran out of values, which would mean the run left the path the
    trace describes

Interrupts are verified rather than forced. Under Renode a run is a
deterministic function of the image and its inputs, so feeding the recorded
values back puts the interrupts where they were; on real silicon it would not,
which is why the trace records their positions and this compares them. See
docs/LIMITS.md.

    python tools/replay.py --seeds 55,130,145
"""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import sys

import gen_run
import renode_run
import trace_format
from campaign import find_renode

REPO = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_WORK = REPO / "build" / "replay"

VERDICT_RE = re.compile(
    r"^control ticks=(\d+) iters=(\d+) torn=(\d+) checksum=(0x[0-9a-f]+)$",
    re.MULTILINE,
)
OUTCOME_RE = re.compile(r"^RUN (OK|FAIL.*)$", re.MULTILINE)


def outcome_of(uart: str) -> dict:
    verdict = VERDICT_RE.search(uart)
    outcome = OUTCOME_RE.search(uart)
    return {
        "ticks": int(verdict.group(1)) if verdict else None,
        "torn": int(verdict.group(3)) if verdict else None,
        "checksum": verdict.group(4) if verdict else None,
        "outcome": outcome.group(1) if outcome else None,
    }


def record(renode: str, seed: int, work: pathlib.Path, run_for: str) -> dict:
    seed_dir = work / f"{seed}-record"
    seed_dir.mkdir(parents=True, exist_ok=True)
    uart_out = seed_dir / "uart.txt"
    if uart_out.exists():
        uart_out.unlink()

    resc = gen_run.generate_resc(seed, seed_dir, uart_out, run_for=run_for)
    proc = renode_run.run_script(renode, resc)
    if not uart_out.exists():
        raise SystemExit(
            f"seed {seed}: recording produced no output: "
            f"{(proc.stderr or proc.stdout)[-300:]}"
        )

    uart = uart_out.read_text(encoding="utf-8", errors="replace")
    data = trace_format.extract_hex_trace(uart)
    events, header = trace_format.parse_device_bytes(data)
    if header["truncated"]:
        raise SystemExit(f"seed {seed}: recording is truncated, nothing to replay")

    # Kept on disk as well as in memory: the trace is the artefact the whole
    # project is about, and it should be possible to look at one.
    trace_path = seed_dir / "trace.bin"
    trace_path.write_bytes(data)

    return {
        "events": events,
        "bytes": len(data),
        "result": outcome_of(uart),
        "trace_path": trace_path,
    }


def replay(renode: str, tag: str, work: pathlib.Path, events: list,
           run_for: str) -> dict:
    replay_dir = work / f"{tag}-replay"
    replay_dir.mkdir(parents=True, exist_ok=True)
    uart_out = replay_dir / "uart.txt"
    exhausted = replay_dir / "overrun.log"
    for stale in (uart_out, exhausted):
        if stale.exists():
            stale.unlink()

    sensor_values = [e.payload for e in events if e.kind == trace_format.KIND_SENSOR]
    jitter_values = [e.payload for e in events if e.kind == trace_format.KIND_JITTER]

    resc = gen_run.generate_replay_resc(
        tag, replay_dir, uart_out, sensor_values, jitter_values, exhausted,
        run_for=run_for,
    )
    proc = renode_run.run_script(renode, resc)
    if not uart_out.exists():
        raise SystemExit(
            f"{tag}: replay produced no output: "
            f"{(proc.stderr or proc.stdout)[-300:]}"
        )

    uart = uart_out.read_text(encoding="utf-8", errors="replace")
    data = trace_format.extract_hex_trace(uart)
    events_out, header = trace_format.parse_device_bytes(data)
    return {
        "events": events_out,
        "result": outcome_of(uart),
        "truncated": header["truncated"],
        "overrun": exhausted.read_text(encoding="ascii", errors="replace").strip()
        if exhausted.exists() else "",
    }


def compare(original: dict, reproduced: dict) -> list[str]:
    problems: list[str] = []

    if reproduced["overrun"]:
        problems.append(
            f"replay ran out of recorded values: {reproduced['overrun'].splitlines()[0]}"
        )
    if reproduced["truncated"]:
        problems.append("replay trace is truncated")

    divergence = trace_format.first_divergence(
        original["events"], reproduced["events"], strict=True
    )
    if divergence is not None:
        index, was, now = divergence
        problems.append(
            f"traces diverge at event {index}: recorded={was.key if was else None} "
            f"replayed={now.key if now else None}"
        )

    for field in ("ticks", "torn", "checksum", "outcome"):
        if original["result"][field] != reproduced["result"][field]:
            problems.append(
                f"{field}: recorded {original['result'][field]!r}, "
                f"replayed {reproduced['result'][field]!r}"
            )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seeds", default="6,34,70,72,144,147,177,182,187,197,239,245,285",
        help="comma-separated seeds; the default is the set the campaign found "
             "the race in",
    )
    parser.add_argument("--renode-dir", default=os.environ.get("RENODE_DIR"))
    parser.add_argument("--run-for", default="0.2")
    parser.add_argument("--work", type=pathlib.Path, default=DEFAULT_WORK)
    parser.add_argument(
        "--require-torn", action="store_true",
        help="also require that each run actually hit the race, so a change "
             "that quietly stopped reproducing it cannot pass unnoticed",
    )
    args = parser.parse_args()

    renode = find_renode(args.renode_dir)
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    status = 0

    for seed in seeds:
        original = record(renode, seed, args.work, args.run_for)
        reproduced = replay(renode, str(seed), args.work, original["events"],
                            args.run_for)
        problems = compare(original, reproduced)

        if args.require_torn and not original["result"]["torn"]:
            problems.append(
                "the recorded run did not hit the race, so reproducing it "
                "demonstrates nothing about the fault"
            )

        if problems:
            status = 1
            print(f"seed {seed}: FAIL")
            for problem in problems:
                print(f"    {problem}")
        else:
            res = original["result"]
            print(
                f"seed {seed}: reproduced  {len(original['events'])} events, "
                f"torn={res['torn']} checksum={res['checksum']} "
                f"verdict={res['outcome']}"
            )

    if status:
        print(
            "\nA run did not reproduce from its trace. Either the trace is "
            "missing something the firmware depends on, or the replay path is "
            "feeding it something the recording did not contain.",
            file=sys.stderr,
        )
    return status


if __name__ == "__main__":
    sys.exit(main())
