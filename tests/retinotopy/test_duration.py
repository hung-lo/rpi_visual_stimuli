from __future__ import annotations

import io
from contextlib import redirect_stdout
import unittest

from rpi_visual_stimuli.core.duration import summarize_protocol_duration
from rpi_visual_stimuli.protocols.retinotopy.config import DEFAULT_DIRECTIONS, FOUR_DIRECTION_MODE, build_config
from rpi_visual_stimuli.protocols.retinotopy.runner import _print_summary
from rpi_visual_stimuli.protocols.retinotopy.sequence import build_trial_sequence, trial_epoch_durations_sec
from tests.helpers import load_repo_system_config


class RetinotopyDurationTests(unittest.TestCase):
    def test_two_direction_default_duration_matches_expected_totals(self):
        system_config = load_repo_system_config()
        config = build_config(system_config, enabled_directions=DEFAULT_DIRECTIONS)
        trials, _ = build_trial_sequence(system_config, config)
        epoch_durations = trial_epoch_durations_sec(trials)
        summary = summarize_protocol_duration(
            trial_epoch_durations_sec=epoch_durations,
            initial_gray_sec=config.initial_gray_sec,
            final_gray_sec=config.final_gray_sec,
            camera_enabled=False,
            baseline_minutes=None,
        )
        self.assertEqual(len(trials), 40)
        self.assertEqual(summary.trial_sequence_sec, 1000.0)
        self.assertEqual(summary.no_camera_protocol_sec, 1006.0)
        self.assertIsNone(summary.camera_start_to_protocol_end_nominal_sec)

        camera_summary = summarize_protocol_duration(
            trial_epoch_durations_sec=epoch_durations,
            initial_gray_sec=config.initial_gray_sec,
            final_gray_sec=config.final_gray_sec,
            camera_enabled=True,
            baseline_minutes=3.0,
        )
        self.assertEqual(camera_summary.camera_start_to_protocol_end_nominal_sec, 1183.0)

    def test_four_direction_default_duration_matches_expected_totals(self):
        system_config = load_repo_system_config()
        config = build_config(system_config, enabled_directions=FOUR_DIRECTION_MODE)
        trials, _ = build_trial_sequence(system_config, config)
        epoch_durations = trial_epoch_durations_sec(trials)
        summary = summarize_protocol_duration(
            trial_epoch_durations_sec=epoch_durations,
            initial_gray_sec=config.initial_gray_sec,
            final_gray_sec=config.final_gray_sec,
            camera_enabled=False,
            baseline_minutes=None,
        )
        self.assertEqual(len(trials), 80)
        self.assertEqual(summary.trial_sequence_sec, 2000.0)
        self.assertEqual(summary.no_camera_protocol_sec, 2006.0)

        camera_summary = summarize_protocol_duration(
            trial_epoch_durations_sec=epoch_durations,
            initial_gray_sec=config.initial_gray_sec,
            final_gray_sec=config.final_gray_sec,
            camera_enabled=True,
            baseline_minutes=3.0,
        )
        self.assertEqual(camera_summary.camera_start_to_protocol_end_nominal_sec, 2183.0)

    def test_summary_prints_duration_labels(self):
        system_config = load_repo_system_config()
        config = build_config(system_config, enabled_directions=DEFAULT_DIRECTIONS)
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
        self.assertIn("Exact planned sweep-sequence duration", output)
        self.assertIn("Nominal camera-start-to-protocol-end duration", output)
