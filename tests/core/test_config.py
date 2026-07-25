from __future__ import annotations

import json
import tempfile
import unittest

from rpi_visual_stimuli.core.config import ConfigurationError, load_system_config
from tests.helpers import repo_root


class ConfigTests(unittest.TestCase):
    def test_load_system_config(self):
        config = load_system_config(repo_root() / "config" / "system_config.json")
        self.assertEqual(config.screen.width_px, 1024)
        self.assertEqual(config.photodiode.corner, "top_right")
        self.assertEqual(str(config.output_root), "/mnt/hd")

    def test_invalid_photodiode_bounds_raise(self):
        payload = json.loads((repo_root() / "config" / "system_config.json").read_text(encoding="utf-8"))
        payload["photodiode"]["size_px"] = 5000
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            temp_path = handle.name
        with self.assertRaises(ConfigurationError):
            load_system_config(temp_path)
