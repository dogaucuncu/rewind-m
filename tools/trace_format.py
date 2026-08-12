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
        """The event as recorded, payload included."""
        return (self.kind, self.payload)

    @property
    def comparable_key(self) -> tuple[str, int | None]:
        """What the device and the oracle can meaningfully be held to agree on.

        Interrupt payloads are excluded. The device records the Cortex-M
        exception number from IPSR, which says which interrupt fired. Renode's
        interrupt hook exposes the classic ARM exception class instead - 5 for
        any IRQ - so the oracle has no way to produce the same number for any
        interrupt at all. Comparing them would be comparing two different facts.

        What still holds, and is still checked, is that interrupts appear the
        same number of times in the same positions: a dropped or reordered
        interrupt shifts the sequence and fails.
        """
        if self.kind == KIND_IRQ:
            return (self.kind, None)
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


class TraceError(ValueError):
    pass


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if pos >= len(data):
            raise TraceError("varint runs past the end of the trace")
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return value, pos
        shift += 7
        if shift > 35:
            raise TraceError("varint longer than a 32-bit value can need")


def parse_device_bytes(data: bytes) -> tuple[list[Event], dict]:
    """Decode the on-device encoding. See docs/TRACE-FORMAT.md.

    Returns the events and the header fields, because a truncated trace is a
    fact about the run that the caller has to be able to act on rather than a
    detail to be smoothed over.
    """
    if len(data) < 8:
        raise TraceError(f"trace is {len(data)} bytes, shorter than its header")
    if data[:4] != MAGIC:
        raise TraceError(f"bad magic {data[:4]!r}, expected {MAGIC!r}")

    header = {
        "version": data[4],
        "truncated": bool(data[5] & 0x01),
    }
    if header["version"] != 1:
        raise TraceError(f"unsupported trace version {header['version']}")

    events: list[Event] = []
    pos = 8
    cycles = 0
    while pos < len(data):
        kind = chr(data[pos])
        pos += 1
        if kind not in KINDS:
            raise TraceError(f"unknown record kind {kind!r} at byte {pos - 1}")
        delta, pos = _read_varint(data, pos)
        payload, pos = _read_varint(data, pos)
        cycles += delta
        events.append(Event(kind=kind, payload=payload, cycles=cycles))
    return events, header


def parse_device_binary(path: pathlib.Path) -> tuple[list[Event], dict]:
    return parse_device_bytes(path.read_bytes())


TRACE_BEGIN = "TRACE BEGIN"
TRACE_END = "TRACE END"


def extract_hex_trace(uart_text: str) -> bytes:
    """Pull the trace out of the UART stream.

    The firmware hex-encodes it between markers because the transport is shared
    with human-readable output. The declared length is checked against what was
    actually received: a run cut short mid-dump would otherwise decode into a
    plausible-looking short trace.
    """
    begin = uart_text.find(TRACE_BEGIN)
    if begin < 0:
        raise TraceError("no trace in the UART output")
    end = uart_text.find(TRACE_END, begin)
    if end < 0:
        raise TraceError("trace was not terminated - the run was cut short")

    header_line, _, body = uart_text[begin:end].partition("\n")
    declared = int(header_line.split()[-1])
    digits = "".join(body.split())
    if len(digits) % 2:
        raise TraceError("odd number of hex digits in the trace")
    data = bytes.fromhex(digits)
    if len(data) != declared:
        raise TraceError(
            f"trace declared {declared} bytes but {len(data)} arrived"
        )
    return data


def counts(events: list[Event]) -> dict[str, int]:
    tally = {kind: 0 for kind in KINDS}
    for event in events:
        tally[event.kind] += 1
    return tally


def first_divergence(
    a: list[Event], b: list[Event], strict: bool = False
) -> tuple[int, Event | None, Event | None] | None:
    """Index of the first differing event, or None if the sequences match.

    Returns the index and both events so a failure can say what it expected and
    what it got, rather than only that something was wrong.

    `strict` includes interrupt payloads. Use it when both sequences come from
    the same producer - comparing a recording against its replay, where the two
    traces really should agree on every field. The default excludes them,
    because the oracle cannot express the recorder's interrupt numbering; see
    Event.comparable_key.
    """
    key = (lambda e: e.key) if strict else (lambda e: e.comparable_key)
    for index in range(max(len(a), len(b))):
        left = a[index] if index < len(a) else None
        right = b[index] if index < len(b) else None
        if left is None or right is None or key(left) != key(right):
            return index, left, right
    return None
