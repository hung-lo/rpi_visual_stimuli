from __future__ import annotations

import io
import os
import threading
import time
import unittest

from rpi_visual_stimuli.core.baseline import (
    start_early_start_monitor,
    stop_early_start_monitor,
    wait_for_prestimulus_gate,
)


class FakeClock:
    def __init__(self, now=0.0):
        self.now_value = now

    def now(self):
        return self.now_value

    def sleep(self, seconds):
        self.now_value += seconds


class BaselineTests(unittest.TestCase):
    def _open_pipe(self):
        read_fd, write_fd = os.pipe()
        reader = os.fdopen(read_fd, "r", buffering=1, encoding="utf-8")
        writer = os.fdopen(write_fd, "w", buffering=1, encoding="utf-8")
        return reader, writer

    def test_timer_elapsed(self):
        clock = FakeClock(now=0.0)
        result = wait_for_prestimulus_gate(
            requested_baseline_seconds=2.0,
            minimum_gray_seconds=1.0,
            baseline_start_monotonic=0.0,
            gray_start_monotonic=0.0,
            now_fn=clock.now,
            sleep_fn=clock.sleep,
            poll_interval_sec=0.5,
        )
        self.assertEqual(result.end_reason, "timer_elapsed")
        self.assertGreaterEqual(result.actual_camera_baseline_seconds, 2.0)

    def test_timer_satisfied_during_preparation(self):
        clock = FakeClock(now=5.0)
        result = wait_for_prestimulus_gate(
            requested_baseline_seconds=2.0,
            minimum_gray_seconds=1.0,
            baseline_start_monotonic=0.0,
            gray_start_monotonic=0.0,
            now_fn=clock.now,
            sleep_fn=clock.sleep,
        )
        self.assertEqual(result.end_reason, "timer_satisfied_during_preparation")

    def test_user_override_still_waits_for_minimum_gray(self):
        clock = FakeClock(now=0.0)
        override = threading.Event()
        override.set()
        result = wait_for_prestimulus_gate(
            requested_baseline_seconds=30.0,
            minimum_gray_seconds=3.0,
            baseline_start_monotonic=0.0,
            gray_start_monotonic=0.0,
            override_event=override,
            now_fn=clock.now,
            sleep_fn=clock.sleep,
            poll_interval_sec=0.5,
        )
        self.assertEqual(result.end_reason, "user_override")
        self.assertTrue(result.waited_for_minimum_gray_after_override)
        self.assertGreaterEqual(result.actual_gray_seconds, 3.0)

    def test_monitor_accepts_y(self):
        reader, writer = self._open_pipe()
        output = io.StringIO()
        monitor = start_early_start_monitor(
            input_stream=reader,
            output_stream=output,
            require_tty=False,
            poll_interval_sec=0.01,
        )
        try:
            writer.write("y\n")
            writer.flush()
            self.assertTrue(monitor.override_event.wait(timeout=1.0))
        finally:
            stop_early_start_monitor(monitor)
            writer.close()
            reader.close()

    def test_monitor_accepts_yes(self):
        reader, writer = self._open_pipe()
        output = io.StringIO()
        monitor = start_early_start_monitor(
            input_stream=reader,
            output_stream=output,
            require_tty=False,
            poll_interval_sec=0.01,
        )
        try:
            writer.write("yes\n")
            writer.flush()
            self.assertTrue(monitor.override_event.wait(timeout=1.0))
        finally:
            stop_early_start_monitor(monitor)
            writer.close()
            reader.close()

    def test_monitor_ignores_blank_input(self):
        reader, writer = self._open_pipe()
        output = io.StringIO()
        monitor = start_early_start_monitor(
            input_stream=reader,
            output_stream=output,
            require_tty=False,
            poll_interval_sec=0.01,
        )
        try:
            writer.write("\n")
            writer.flush()
            time.sleep(0.05)
            self.assertFalse(monitor.override_event.is_set())
        finally:
            stop_early_start_monitor(monitor)
            writer.close()
            reader.close()

    def test_monitor_ignores_unrelated_input(self):
        reader, writer = self._open_pipe()
        output = io.StringIO()
        monitor = start_early_start_monitor(
            input_stream=reader,
            output_stream=output,
            require_tty=False,
            poll_interval_sec=0.01,
        )
        try:
            writer.write("maybe\n")
            writer.flush()
            time.sleep(0.05)
            self.assertFalse(monitor.override_event.is_set())
            self.assertIn("Ignoring input", output.getvalue())
        finally:
            stop_early_start_monitor(monitor)
            writer.close()
            reader.close()

    def test_stopping_monitor_without_input_terminates_thread(self):
        reader, writer = self._open_pipe()
        output = io.StringIO()
        monitor = start_early_start_monitor(
            input_stream=reader,
            output_stream=output,
            require_tty=False,
            poll_interval_sec=0.01,
        )
        try:
            stop_early_start_monitor(monitor)
            if monitor.thread is not None:
                self.assertFalse(monitor.thread.is_alive())
        finally:
            writer.close()
            reader.close()

    def test_subsequent_prompt_receives_its_own_input(self):
        reader, writer = self._open_pipe()
        output = io.StringIO()
        monitor = start_early_start_monitor(
            input_stream=reader,
            output_stream=output,
            require_tty=False,
            poll_interval_sec=0.01,
        )
        try:
            writer.write("n\n")
            writer.flush()
            time.sleep(0.05)
            stop_early_start_monitor(monitor)
            writer.write("later\n")
            writer.flush()
            self.assertEqual(reader.readline(), "later\n")
        finally:
            writer.close()
            reader.close()

    def test_monitor_eof_does_not_crash(self):
        reader, writer = self._open_pipe()
        output = io.StringIO()
        monitor = start_early_start_monitor(
            input_stream=reader,
            output_stream=output,
            require_tty=False,
            poll_interval_sec=0.01,
        )
        try:
            writer.close()
            if monitor.thread is not None:
                monitor.thread.join(timeout=1.0)
                self.assertFalse(monitor.thread.is_alive())
            self.assertFalse(monitor.override_event.is_set())
        finally:
            stop_early_start_monitor(monitor)
            reader.close()
