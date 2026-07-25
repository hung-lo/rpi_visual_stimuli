from __future__ import annotations

import io
from contextlib import redirect_stdout
import unittest

from rpi_visual_stimuli.core.duration import summarize_protocol_duration
from rpi_visual_stimuli.protocols.drifting_gratings.config import build_config
from rpi_visual_stimuli.protocols.drifting_gratings.runner import _print_summary
from rpi_visual_stimuli.protocols.drifting_gratings.sequence import build_trial_sequence, trial_epoch_durations_sec
from tests.helpers import load_repo_system_config


class DriftingGratingDurationTests(unittest.TestCase):
    def test_default_duration_summary_matches_exact_trial_sequence(self):
        system_config = load_repo_system_config()
        config = build_config(system_config, sequence_seed=123)
        trials, _ = build_trial_sequence(system_config, config)
        epoch_durations = trial_epoch_durations_sec(trials)
        summary = summarize_protocol_duration(
            trial_epoch_durations_sec=epoch_durations,
            initial_gray_sec=config.initial_gray_sec,
            final_gray_sec=config.final_gray_sec,
            camera_enabled=False,
            baseline_minutes=None,
        )
        self.assertEqual(len(trials), 640)
        self.assertAlmostEqual(summary.trial_sequence_sec, sum(epoch_durations))
        self.assertGreaterEqual(summary.no_camera_protocol_sec, 774.0)
        self.assertLessEqual(summary.no_camera_protocol_sec, 1094.0)
        self.assertIsNone(summary.camera_start_to_protocol_end_nominal_sec)

    def test_camera_duration_adds_requested_baseline_to_exact_trial_sequence(self):
        system_config = load_repo_system_config()
        config = build_config(system_config, sequence_seed=123)
        trials, _ = build_trial_sequence(system_config, config)
        epoch_durations = trial_epoch_durations_sec(trials)
        summary = summarize_protocol_duration(
            trial_epoch_durations_sec=epoch_durations,
            initial_gray_sec=config.initial_gray_sec,
            final_gray_sec=config.final_gray_sec,
            camera_enabled=True,
            baseline_minutes=3.0,
        )
        self.assertAlmostEqual(
            summary.camera_start_to_protocol_end_nominal_sec or 0.0,
            180.0 + sum(epoch_durations) + config.final_gray_sec,
        )

    def test_summary_prints_duration_labels(self):
        system_config = load_repo_system_config()
        config = build_config(system_config, sequence_seed=123)
        trials, _ = build_trial_sequence(system_config, config)
        summary = summarize_protocol_duration(
            trial_epoch_durations_sec=trial_epoch_durations_sec(trials),
            initial_gray_sec=config.initial_gray_sec,
            final_gray_sec=config.final_gray_sec,
            camera_enabled=True,
            baseline_minutes=3.0,
        )
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            _print_summary(system_config, config, trials, True, 3.0, summary)
        output = buffer.getvalue()
        self.assertIn("Exact planned trial-sequence duration", output)
        self.assertIn("Nominal camera-start-to-protocol-end duration", output)

