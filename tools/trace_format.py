#!/usr/bin/env python3
"""The only place a trace encoding is interpreted.

Two producers write traces — the emulator oracle (M2, text) and the in-firmware
recorder (M3, binary) — and the whole point of the differential check is that
they are compared without either side getting to define what "equal" means. So
both decode through here, into the same events, and the comparison happens on
the decoded form.

See docs/TRACE-FORMAT.md.
"""

from __future__ import annotations

import dataclasses
import pathlib

KIND_SENSOR = "S"
KIND_JITTER = "J"
KIND_IRQ = "I"
KIND_GAP = "G"

KINDS = (KIND_SENSOR, KIND_JITTER, KIND_IRQ, KIND_GAP)

MAGIC = b"RWM1"


@dataclasses.dataclass(frozen=True)
class Event:
    kind: str
    payload: int
    # Cycle timestamp, when the producer has one. Deliberately excluded from
    # equality: the oracle observes from outside the CPU and cannot read DWT
    # without perturbing the machine it is meant to watch neutrally.
    cycles: int | None = None

    @property
    def key(self) -> tuple[str, int]:
        """What equality is defined on."""
        return (self.kind, self.payload)


def parse_oracle_text(path: pathlib.Path) -> list[Event]:
    """Decode the oracle's text encoding.

    Written by Renode hooks one line at a time, so a truncated final line is a
    real possibility if a run is cut short; that is reported rather than
    silently dropped.
    """
    events: list[Event] = []
    raw = path.read_text(encoding="ascii", errors="replace")
    for lineno, line in enumerate(raw.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2 or parts[0] not in KINDS:
            raise ValueError(f"{path}:{lineno}: cannot parse {line!r}")
        events.append(Event(kind=parts[0], payload=int(parts[1])))
    return events


def parse_device_binary(path: pathlib.Path) -> list[Event]:
    """Decode the on-device encoding. Implemented in M3, specified now."""
    raise NotImplementedError(
        "the device recorder lands in M3; docs/TRACE-FORMAT.md has the encoding"
    )


def counts(events: list[Event]) -> dict[str, int]:
    tally = {kind: 0 for kind in KINDS}
    for event in events:
        tally[event.kind] += 1
    return tally


def first_divergence(a: list[Event], b: list[Event]) -> tuple[int, Event | None, Event | None] | None:
    """Index of the first differing event, or None if the sequences match.

    Returns the index and both events so a failure can say what it expected and
    what it got, rather than only that something was wrong.
    """
    for index in range(max(len(a), len(b))):
        left = a[index] if index < len(a) else None
        right = b[index] if index < len(b) else None
        if left is None or right is None or left.key != right.key:
            return index, left, right
    return None
