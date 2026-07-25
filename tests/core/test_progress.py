from __future__ import annotations

import unittest

from rpi_visual_stimuli.core.progress import ProgressReporter, render_progress_line


class _FakeStream:
    def __init__(self, *, interactive: bool):
        self._interactive = interactive
        self.writes: list[str] = []
        self.flush_count = 0

    def write(self, text: str) -> None:
        self.writes.append(text)

    def flush(self) -> None:
        self.flush_count += 1

    def isatty(self) -> bool:
        return self._interactive

    def joined(self) -> str:
        return "".join(self.writes)


class ProgressTests(unittest.TestCase):
    def test_render_progress_line_shows_zero_progress(self):
        line = render_progress_line(
            current_index=0,
            total_count=10,
            current_condition="waiting",
            elapsed_seconds=0.0,
            remaining_seconds=12.0,
        )
        self.assertIn("[--------------------]", line)
        self.assertIn("0/10", line)
        self.assertIn("0.0%", line)
        self.assertIn("elapsed 0:00", line)
        self.assertIn("ETA 0:12", line)

    def test_render_progress_line_shows_half_progress(self):
        line = render_progress_line(
            current_index=5,
            total_count=10,
            current_condition="midpoint",
            elapsed_seconds=10.0,
            remaining_seconds=10.0,
        )
        self.assertIn("[##########----------]", line)
        self.assertIn("5/10", line)
        self.assertIn("50.0%", line)

    def test_render_progress_line_shows_complete_progress(self):
        line = render_progress_line(
            current_index=10,
            total_count=10,
            current_condition="final_gray",
            elapsed_seconds=90.0,
            remaining_seconds=0.0,
        )
        self.assertIn("[####################]", line)
        self.assertIn("10/10", line)
        self.assertIn("100.0%", line)
        self.assertIn("ETA 0:00", line)

    def test_render_progress_line_clamps_fraction_and_remaining(self):
        line = render_progress_line(
            current_index=12,
            total_count=10,
            current_condition="done",
            elapsed_seconds=65.0,
            remaining_seconds=-3.0,
        )
        self.assertIn("[####################]", line)
        self.assertIn("100.0%", line)
        self.assertIn("elapsed 1:05", line)
        self.assertIn("ETA 0:00", line)

    def test_render_progress_line_clamps_negative_fraction(self):
        line = render_progress_line(
            current_index=-2,
            total_count=10,
            current_condition="prestart",
            elapsed_seconds=1.0,
            remaining_seconds=9.0,
        )
        self.assertIn("[--------------------]", line)
        self.assertIn("0.0%", line)

    def test_progress_reporter_clears_shorter_replacement_lines(self):
        stream = _FakeStream(interactive=True)
        reporter = ProgressReporter(total_count=10, stream=stream)
        reporter.update(
            current_index=9,
            current_condition="direction=left_to_right",
            elapsed_seconds=10.0,
            remaining_seconds=5.0,
        )
        reporter.update(
            current_index=10,
            current_condition="done",
            elapsed_seconds=11.0,
            remaining_seconds=0.0,
        )
        self.assertEqual(len(stream.writes), 2)
        self.assertTrue(stream.writes[0].startswith("\r"))
        self.assertTrue(stream.writes[1].startswith("\r"))
        self.assertTrue(stream.writes[1].endswith(" "))

    def test_progress_reporter_finish_writes_single_newline(self):
        stream = _FakeStream(interactive=True)
        reporter = ProgressReporter(total_count=1, stream=stream)
        reporter.update(
            current_index=0,
            current_condition="waiting",
            elapsed_seconds=0.0,
            remaining_seconds=1.0,
        )
        reporter.finish()
        reporter.finish()
        self.assertTrue(stream.joined().endswith("\n"))
        self.assertEqual(stream.joined().count("\n"), 1)

    def test_non_interactive_progress_uses_newline_delimited_output(self):
        stream = _FakeStream(interactive=False)
        reporter = ProgressReporter(total_count=2, stream=stream)
        reporter.update(
            current_index=0,
            current_condition="waiting",
            elapsed_seconds=0.0,
            remaining_seconds=4.0,
        )
        reporter.update(
            current_index=2,
            current_condition="final_gray",
            elapsed_seconds=4.0,
            remaining_seconds=0.0,
        )
        reporter.finish()
        output = stream.joined()
        self.assertNotIn("\r", output)
        self.assertEqual(output.count("\n"), 2)
        self.assertIn("0/2", output)
        self.assertIn("2/2", output)

