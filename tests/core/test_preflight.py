from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rpi_visual_stimuli.core.preflight import check_disk_space_before_build, check_memory_before_loading, read_meminfo


class PreflightTests(unittest.TestCase):
    def test_read_meminfo_parses_bytes(self):
        content = "MemTotal:       1024 kB\nMemAvailable:    256 kB\n"
        with tempfile.NamedTemporaryFile("w", delete=False) as handle:
            handle.write(content)
            path = handle.name
        meminfo = read_meminfo(path)
        self.assertEqual(meminfo["MemTotal"], 1024 * 1024)
        self.assertEqual(meminfo["MemAvailable"], 256 * 1024)

    def test_memory_check_reports_shortfall(self):
        with self.assertRaises(MemoryError) as ctx:
            check_memory_before_loading(
                [100, 100],
                available_memory_bytes=100,
                overhead_factor=1.15,
                safety_margin_bytes=50,
            )
        self.assertIn("shortfall", str(ctx.exception))

    def test_disk_check_uses_margin(self):
        with mock.patch("rpi_visual_stimuli.core.preflight.shutil.disk_usage") as fake_usage:
            fake_usage.return_value = (1000, 100, 900)
            result = check_disk_space_before_build(Path("."), required_bytes=100, margin_bytes=100)
        self.assertEqual(result.shortfall_bytes, 0)
