"""Unit tests for the trace decoder, the comparator, and the replay generator.

These exist because the comparator is the thing every other claim rests on. If
`first_divergence` always returned None, CI would be green, the README would say
the traces match, and none of it would mean anything. So the tests here are
mostly about proving the check can *fail* - a comparison that has never rejected
anything is not evidence.

    python -m unittest discover -s tests -t .
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))

import gen_run  # noqa: E402
import trace_format as tf  # noqa: E402


def varint(value: int) -> bytes:
    out = bytearray()
    while value >= 0x80:
        out.append((value | 0x80) & 0xFF)
        value >>= 7
    out.append(value)
    return bytes(out)


def device_trace(records, truncated=False):
    """Build a device-encoded trace from (kind, delta, payload) tuples."""
    body = b"".join(
        kind.encode("ascii") + varint(delta) + varint(payload)
        for kind, delta, payload in records
    )
    flags = 0x01 if truncated else 0x00
    return tf.MAGIC + bytes([1, flags, 0, 0]) + body


SAMPLE = [("S", 10, 2043), ("I", 5, 44), ("J", 7, 0xDEADBEEF), ("S", 3, 2044)]


class DecoderTests(unittest.TestCase):
    def test_round_trip(self):
        events, header = tf.parse_device_bytes(device_trace(SAMPLE))
        self.assertEqual([e.key for e in events],
                         [("S", 2043), ("I", 44), ("J", 0xDEADBEEF), ("S", 2044)])
        self.assertFalse(header["truncated"])
        # Deltas accumulate into absolute cycle counts.
        self.assertEqual([e.cycles for e in events], [10, 15, 22, 25])

    def test_truncated_flag_is_surfaced(self):
        _, header = tf.parse_device_bytes(device_trace(SAMPLE, truncated=True))
        self.assertTrue(header["truncated"])

    def test_rejects_bad_magic(self):
        data = bytearray(device_trace(SAMPLE))
        data[0:4] = b"NOPE"
        with self.assertRaises(tf.TraceError):
            tf.parse_device_bytes(bytes(data))

    def test_rejects_unknown_version(self):
        data = bytearray(device_trace(SAMPLE))
        data[4] = 99
        with self.assertRaises(tf.TraceError):
            tf.parse_device_bytes(bytes(data))

    def test_rejects_unknown_record_kind(self):
        data = bytearray(device_trace(SAMPLE))
        data[8] = ord("Z")
        with self.assertRaises(tf.TraceError):
            tf.parse_device_bytes(bytes(data))

    def test_rejects_varint_past_the_end(self):
        # A record header with a varint that never terminates.
        data = tf.MAGIC + bytes([1, 0, 0, 0]) + b"S" + b"\x80\x80"
        with self.assertRaises(tf.TraceError):
            tf.parse_device_bytes(data)

    def test_rejects_trace_shorter_than_its_header(self):
        with self.assertRaises(tf.TraceError):
            tf.parse_device_bytes(b"RWM")


class HexExtractionTests(unittest.TestCase):
    def wrap(self, data: bytes, declared=None) -> str:
        declared = len(data) if declared is None else declared
        return (
            "rewind-m M0 smoke test\r\n"
            f"TRACE BEGIN {declared}\r\n{data.hex()}\r\nTRACE END\r\n"
            "RUN OK\r\n"
        )

    def test_extracts_between_markers(self):
        data = device_trace(SAMPLE)
        self.assertEqual(tf.extract_hex_trace(self.wrap(data)), data)

    def test_rejects_length_mismatch(self):
        # A run cut short mid-dump would otherwise decode into a short trace
        # that parses perfectly and is missing the end of the run.
        data = device_trace(SAMPLE)
        with self.assertRaises(tf.TraceError):
            tf.extract_hex_trace(self.wrap(data, declared=len(data) + 4))

    def test_rejects_missing_end_marker(self):
        data = device_trace(SAMPLE)
        text = f"TRACE BEGIN {len(data)}\r\n{data.hex()}\r\n"
        with self.assertRaises(tf.TraceError):
            tf.extract_hex_trace(text)

    def test_rejects_absent_trace(self):
        with self.assertRaises(tf.TraceError):
            tf.extract_hex_trace("nothing here\r\n")


class ComparatorTests(unittest.TestCase):
    """The point of the whole exercise: this must be able to say no."""

    def setUp(self):
        self.events, _ = tf.parse_device_bytes(device_trace(SAMPLE))

    def test_identical_sequences_agree(self):
        other, _ = tf.parse_device_bytes(device_trace(SAMPLE))
        self.assertIsNone(tf.first_divergence(self.events, other))

    def test_detects_a_dropped_event(self):
        missing = self.events[:2] + self.events[3:]
        result = tf.first_divergence(self.events, missing)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 2)

    def test_detects_a_reordered_pair(self):
        swapped = list(self.events)
        swapped[0], swapped[2] = swapped[2], swapped[0]
        result = tf.first_divergence(self.events, swapped)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 0)

    def test_detects_a_changed_payload(self):
        altered = list(self.events)
        altered[0] = tf.Event(kind="S", payload=9999)
        result = tf.first_divergence(self.events, altered)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 0)

    def test_detects_a_truncated_tail(self):
        result = tf.first_divergence(self.events, self.events[:-1])
        self.assertIsNotNone(result)
        self.assertEqual(result[0], len(self.events) - 1)

    def test_detects_an_extra_event(self):
        longer = self.events + [tf.Event(kind="S", payload=1)]
        result = tf.first_divergence(self.events, longer)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], len(self.events))

    def test_ignores_interrupt_payloads(self):
        # Documented exclusion: the device records the Cortex-M exception number
        # and Renode's hook reports the ARM exception class, so the two cannot
        # mean the same thing by this field.
        other = list(self.events)
        other[1] = tf.Event(kind="I", payload=5)
        self.assertIsNone(tf.first_divergence(self.events, other))

    def test_still_detects_a_missing_interrupt(self):
        # Excluding the payload must not excuse losing the event itself.
        without = [e for e in self.events if e.kind != "I"]
        self.assertIsNotNone(tf.first_divergence(self.events, without))

    def test_ignores_timestamps(self):
        shifted = [tf.Event(kind=e.kind, payload=e.payload, cycles=e.cycles + 1000)
                   for e in self.events]
        self.assertIsNone(tf.first_divergence(self.events, shifted))


class OracleTextTests(unittest.TestCase):
    def test_parses_and_counts(self):
        path = pathlib.Path(__file__).with_name("_tmp_oracle.trace")
        path.write_text("S 2043\nI 5\nJ 3735928559\n", encoding="ascii")
        try:
            events = tf.parse_oracle_text(path)
            self.assertEqual(tf.counts(events), {"S": 1, "J": 1, "I": 1, "G": 0})
        finally:
            path.unlink()

    def test_rejects_a_malformed_line(self):
        path = pathlib.Path(__file__).with_name("_tmp_bad.trace")
        path.write_text("S 2043\nnonsense\n", encoding="ascii")
        try:
            with self.assertRaises(ValueError):
                tf.parse_oracle_text(path)
        finally:
            path.unlink()


class ReplayGeneratorTests(unittest.TestCase):
    """The replay peripheral must not be able to reach a seed.

    This guard was written once with a corrupted regex - a stray escape made it
    match "SEED" followed by a backspace character, so it could never fire. It
    looked correct in review. It is tested here because a guard nobody has seen
    reject anything is not a guard.
    """

    def test_bakes_values_without_a_seed(self):
        src = gen_run.render_replay([7, 8, 9], pathlib.Path("overrun.log"))
        self.assertIn("VALUES = [7,8,9]", src)
        self.assertFalse(
            any(line.startswith("SEED") for line in src.splitlines())
        )

    def test_refuses_a_peripheral_carrying_a_seed(self):
        source = gen_run.REPLAY_SRC
        original = source.read_text(encoding="utf-8")
        # Built by concatenation rather than with an escape: a corrupted escape
        # is what broke this guard in the first place.
        seeded = "SEED = 1234" + chr(10) + original
        source.write_text(seeded, encoding="utf-8")
        try:
            with self.assertRaises(SystemExit):
                gen_run.render_replay([1], pathlib.Path("overrun.log"))
        finally:
            source.write_text(original, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
