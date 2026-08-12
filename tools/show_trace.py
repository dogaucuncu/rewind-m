#!/usr/bin/env python3
"""Print a trace in a form a person can read.

Useful on its own when something diverges, and it is what makes the demo
concrete: a trace is not an abstraction, it is a few thousand bytes you can look
at.

    python tools/show_trace.py build/replay/6-record/trace.bin --head 12
"""

from __future__ import annotations

import argparse
import pathlib
import sys

import trace_format

LABELS = {
    trace_format.KIND_SENSOR: "sensor read",
    trace_format.KIND_JITTER: "jitter read",
    trace_format.KIND_IRQ: "interrupt",
    trace_format.KIND_GAP: "GAP - events lost",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=pathlib.Path)
    parser.add_argument("--head", type=int, default=10,
                        help="how many events to print (0 for all)")
    args = parser.parse_args()

    try:
        events, header = trace_format.parse_device_binary(args.trace)
    except trace_format.TraceError as exc:
        print(f"{args.trace}: {exc}", file=sys.stderr)
        return 1

    size = args.trace.stat().st_size
    tally = trace_format.counts(events)
    print(f"{args.trace}: {size} bytes, {len(events)} events"
          + (" (TRUNCATED)" if header["truncated"] else ""))
    print(f"  sensor {tally['S']}  jitter {tally['J']}  "
          f"interrupts {tally['I']}  gaps {tally['G']}")
    print()

    shown = events if args.head == 0 else events[:args.head]
    print(f"{'#':>5}  {'cycle':>10}  {'event':<18}  value")
    for index, event in enumerate(shown):
        print(f"{index:>5}  {event.cycles:>10}  {LABELS[event.kind]:<18}  "
              f"{event.payload}")
    if len(shown) < len(events):
        print(f"  ... {len(events) - len(shown)} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
