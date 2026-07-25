from __future__ import annotations

import collections
import unittest

from rpi_visual_stimuli.protocols.drifting_gratings.config import build_config
from rpi_visual_stimuli.protocols.drifting_gratings.sequence import build_trial_sequence
from tests.helpers import load_repo_system_config


class DriftingGratingSequenceTests(unittest.TestCase):
    def test_default_sequence_has_640_trials_and_80_per_orientation(self):
        system_config = load_repo_system_config()
        config = build_config(system_config, sequence_seed=123)
        trials, _seed = build_trial_sequence(system_config, config)
        self.assertEqual(len(trials), 640)
        counts = collections.Counter(trial["orientation_id"] for trial in trials)
        self.assertEqual(set(counts.values()), {80})

    def test_seed_reproducibility(self):
        system_config = load_repo_system_config()
        config_a = build_config(system_config, sequence_seed=123)
        config_b = build_config(system_config, sequence_seed=123)
        config_c = build_config(system_config, sequence_seed=456)
        trials_a, _ = build_trial_sequence(system_config, config_a)
        trials_b, _ = build_trial_sequence(system_config, config_b)
        trials_c, _ = build_trial_sequence(system_config, config_c)
        self.assertEqual(
            [trial["orientation_id"] for trial in trials_a],
            [trial["orientation_id"] for trial in trials_b],
        )
        self.assertNotEqual(
            [trial["orientation_id"] for trial in trials_a],
            [trial["orientation_id"] for trial in trials_c],
        )
