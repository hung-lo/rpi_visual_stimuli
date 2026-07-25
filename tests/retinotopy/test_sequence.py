from __future__ import annotations

import unittest

from rpi_visual_stimuli.protocols.retinotopy.config import DEFAULT_DIRECTIONS, FOUR_DIRECTION_MODE, build_config
from rpi_visual_stimuli.protocols.retinotopy.sequence import build_trial_sequence
from tests.helpers import load_repo_system_config


class RetinotopySequenceTests(unittest.TestCase):
    def test_two_direction_fixed_order_alternates(self):
        system_config = load_repo_system_config()
        config = build_config(system_config, enabled_directions=DEFAULT_DIRECTIONS, repeats_per_direction=2)
        trials, _ = build_trial_sequence(system_config, config)
        self.assertEqual([trial["direction"] for trial in trials], ["left_to_right", "top_to_bottom", "left_to_right", "top_to_bottom"])

    def test_four_direction_shuffle_preserves_balance(self):
        system_config = load_repo_system_config()
        config = build_config(
            system_config,
            enabled_directions=FOUR_DIRECTION_MODE,
            repeats_per_direction=2,
            sequence_order_mode="shuffled",
            sequence_seed=7,
        )
        trials, _ = build_trial_sequence(system_config, config)
        self.assertEqual(len(trials), 8)
        for repeat_index in range(2):
            repeat_slice = trials[repeat_index * 4 : (repeat_index + 1) * 4]
            self.assertEqual(set(item["direction"] for item in repeat_slice), set(FOUR_DIRECTION_MODE))
