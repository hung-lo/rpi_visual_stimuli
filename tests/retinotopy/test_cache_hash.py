from __future__ import annotations

from dataclasses import replace
import unittest

from rpi_visual_stimuli.protocols.retinotopy.cache import build_cache_hash_payload
from rpi_visual_stimuli.protocols.retinotopy.config import build_test_config
from tests.helpers import load_repo_system_config


class RetinotopyCacheHashTests(unittest.TestCase):
    def test_resolution_changes_cache_hash_payload(self):
        system_config = load_repo_system_config()
        config = build_test_config(system_config)
        changed_screen = replace(system_config.screen, width_px=1024, height_px=600)
        changed_config = replace(system_config, screen=changed_screen)
        self.assertNotEqual(
            build_cache_hash_payload(system_config, config),
            build_cache_hash_payload(changed_config, config),
        )

    def test_viewer_geometry_does_not_change_render_cache_payload(self):
        system_config = load_repo_system_config()
        config = build_test_config(system_config)
        changed_geometry = replace(
            system_config.viewer_geometry,
            screen_yaw_deg=12.0,
        )
        changed_config = replace(system_config, viewer_geometry=changed_geometry)
        self.assertEqual(
            build_cache_hash_payload(system_config, config),
            build_cache_hash_payload(changed_config, config),
        )
