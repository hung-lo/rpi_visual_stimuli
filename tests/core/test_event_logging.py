from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from rpi_visual_stimuli.core.event_logging import append_csv_row, write_csv


class EventLoggingTests(unittest.TestCase):
    def test_write_csv_and_append_csv_row(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "events.csv"
            fieldnames = ["utc_iso", "unix_time_utc_sec", "event_type", "notes"]
            write_csv(path, [{"event_type": "first", "notes": "alpha"}], fieldnames)
            append_csv_row(path, {"event_type": "second", "notes": "beta"}, fieldnames)
            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["event_type"], "first")
        self.assertEqual(rows[1]["event_type"], "second")
        self.assertTrue(rows[1]["utc_iso"])
