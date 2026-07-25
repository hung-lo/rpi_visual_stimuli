from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rpi_visual_stimuli.core.raw_conversion import convert_rgb_frames_to_raw


class RawConversionTests(unittest.TestCase):
    def test_temporary_files_are_cleaned_on_success(self):
        def fake_convert(source_path, converted_path, *_args):
            Path(converted_path).write_bytes(Path(source_path).read_bytes()[:4] or b"raw0")

        with tempfile.TemporaryDirectory() as temp_dir:
            final_path = Path(temp_dir) / "movie.raw"
            frame = bytes([0, 1, 2] * 4)
            result = convert_rgb_frames_to_raw(
                [frame, frame],
                frame_count=2,
                width_px=2,
                height_px=2,
                refreshes_per_source_frame=1,
                colormode=16,
                final_path=final_path,
                convert_raw_fn=fake_convert,
            )
            leftovers = [path.name for path in Path(temp_dir).iterdir() if path.name != "movie.raw"]
        self.assertEqual(result.path, final_path)
        self.assertFalse(leftovers)

    def test_temporary_files_are_cleaned_on_exception(self):
        def fake_convert(_source_path, _converted_path, *_args):
            raise RuntimeError("boom")

        with tempfile.TemporaryDirectory() as temp_dir:
            final_path = Path(temp_dir) / "movie.raw"
            frame = bytes([0, 1, 2] * 4)
            with self.assertRaises(RuntimeError):
                convert_rgb_frames_to_raw(
                    [frame],
                    frame_count=1,
                    width_px=2,
                    height_px=2,
                    refreshes_per_source_frame=1,
                    colormode=16,
                    final_path=final_path,
                    convert_raw_fn=fake_convert,
                )
            leftovers = list(Path(temp_dir).iterdir())
        self.assertFalse(leftovers)
