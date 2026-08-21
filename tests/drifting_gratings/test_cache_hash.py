from __future__ import annotations

from dataclasses import replace
import unittest

from rpi_visual_stimuli.protocols.drifting_gratings.cache import build_cache_hash_payload
from rpi_visual_stimuli.protocols.drifting_gratings.config import build_test_config
from tests.helpers import load_repo_system_config


class DriftingGratingsCacheHashTests(unittest.TestCase):
    def test_resolution_changes_cache_hash_payload(self):
        system_config = load_repo_system_config()
        config = build_test_config(system_config)
        changed_screen = replace(system_config.screen, width_px=1024, height_px=600)
        changed_config = replace(system_config, screen=changed_screen)
        self.assertNotEqual(
            build_cache_hash_payload(system_config, config),
            build_cache_hash_payload(changed_config, config),
        )

    def test_physical_calibration_changes_cache_hash_payload(self):
        system_config = load_repo_system_config()
        config = build_test_config(system_config)
        changed_screen = replace(system_config.screen, visible_width_cm=53.1456)
        changed_config = replace(system_config, screen=changed_screen)
        self.assertNotEqual(
            build_cache_hash_payload(system_config, config),
            build_cache_hash_payload(changed_config, config),
        )
