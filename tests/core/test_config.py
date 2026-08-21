from __future__ import annotations

import json
import tempfile
import unittest

from rpi_visual_stimuli.core.config import ConfigurationError, load_system_config
from tests.helpers import repo_root


class ConfigTests(unittest.TestCase):
    def test_load_system_config(self):
        config = load_system_config(repo_root() / "config" / "system_config.json")
        self.assertEqual(config.screen.width_px, 1280)
        self.assertEqual(config.screen.height_px, 720)
        self.assertEqual(config.screen.visible_width_cm, 15.50)
        self.assertEqual(config.screen.visible_height_cm, 8.72)
        self.assertEqual(config.photodiode.corner, "top_right")
        self.assertEqual(str(config.output_root), "/mnt/hd")
        self.assertEqual(config.viewer_geometry.screen_model, "Desview OL7")
        self.assertEqual(config.viewer_geometry.eye_screen_distance_cm, 16.0)
        self.assertEqual(config.viewer_geometry.geometry_source, "assumed_centered_orthogonal")

    def test_invalid_photodiode_bounds_raise(self):
        payload = json.loads((repo_root() / "config" / "system_config.json").read_text(encoding="utf-8"))
        payload["photodiode"]["size_px"] = 5000
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            temp_path = handle.name
        with self.assertRaises(ConfigurationError):
            load_system_config(temp_path)
