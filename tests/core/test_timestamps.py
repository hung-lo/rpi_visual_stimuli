from __future__ import annotations

import unittest

from rpi_visual_stimuli.core.timestamps import unix_ns_to_iso, unix_ns_to_seconds_string


class TimestampTests(unittest.TestCase):
    def test_unix_ns_to_iso_preserves_nine_digits(self):
        self.assertEqual(
            unix_ns_to_iso(1_700_000_000_123_456_789),
            "2023-11-14T22:13:20.123456789+00:00",
        )

    def test_unix_ns_to_seconds_string_preserves_nine_digits(self):
        self.assertEqual(
            unix_ns_to_seconds_string(1_700_000_000_123_456_789),
            "1700000000.123456789",
        )
