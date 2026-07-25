from __future__ import annotations

import unittest
from unittest.mock import patch

from rpi_visual_stimuli.core import camera as camera_core
from tests.helpers import load_repo_system_config


def _result(*, name: str, returncode: int = 0, stdout: str = "", stderr: str = "") -> camera_core.CameraCommandResult:
    return camera_core.CameraCommandResult(
        command=("python3", "remote_camera_control.py", name),
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


class CameraCleanupTests(unittest.TestCase):
    def setUp(self):
        self.system_config = load_repo_system_config()

    def test_cleanup_order_is_stop_then_sleep_then_fetch_then_convert(self):
        call_order: list[str] = []

        def stop_side_effect(*args, **kwargs):
            call_order.append("stop")
            return _result(name="stop")

        def sleep_side_effect(seconds):
            call_order.append(f"sleep:{seconds}")

        def fetch_side_effect(*args, **kwargs):
            call_order.append("fetch")
            return _result(name="fetch")

        def convert_side_effect(*args, **kwargs):
            call_order.append("convert")
            return _result(name="convert")

        with patch.object(camera_core, "stop_camera", side_effect=stop_side_effect), patch.object(
            camera_core.time, "sleep", side_effect=sleep_side_effect
        ), patch.object(camera_core, "fetch_camera", side_effect=fetch_side_effect), patch.object(
            camera_core, "convert_camera", side_effect=convert_side_effect
        ):
            result = camera_core.stop_and_fetch_camera(
                self.system_config.camera,
                self.system_config.output_root,
                settle_seconds=2.5,
            )

        self.assertEqual(call_order, ["stop", "sleep:2.5", "fetch", "convert"])
        self.assertTrue(result.stop_result.succeeded)
        self.assertTrue(result.fetch_result.succeeded)
        self.assertTrue(result.convert_result.succeeded)
        self.assertEqual(result.settle_seconds, 2.5)
        self.assertIsNone(result.cleanup_error)

    def test_fetch_and_convert_are_skipped_when_stop_fails(self):
        with patch.object(camera_core, "stop_camera", return_value=_result(name="stop", returncode=1, stderr="stop failed")), patch.object(
            camera_core.time, "sleep"
        ) as sleep_mock, patch.object(camera_core, "fetch_camera") as fetch_mock, patch.object(
            camera_core, "convert_camera"
        ) as convert_mock:
            result = camera_core.stop_and_fetch_camera(
                self.system_config.camera,
                self.system_config.output_root,
                settle_seconds=2.0,
            )

        sleep_mock.assert_not_called()
        fetch_mock.assert_not_called()
        convert_mock.assert_not_called()
        self.assertEqual(result.stop_result.returncode, 1)
        self.assertIsNone(result.fetch_result)
        self.assertIsNone(result.convert_result)
        self.assertEqual(result.settle_seconds, 0.0)
        self.assertIn("stop failed", result.cleanup_error)

    def test_convert_is_skipped_when_fetch_fails(self):
        with patch.object(camera_core, "stop_camera", return_value=_result(name="stop")), patch.object(
            camera_core.time, "sleep"
        ) as sleep_mock, patch.object(
            camera_core,
            "fetch_camera",
            return_value=_result(name="fetch", returncode=1, stderr="fetch failed"),
        ) as fetch_mock, patch.object(camera_core, "convert_camera") as convert_mock:
            result = camera_core.stop_and_fetch_camera(
                self.system_config.camera,
                self.system_config.output_root,
                settle_seconds=1.0,
            )

        sleep_mock.assert_called_once_with(1.0)
        fetch_mock.assert_called_once()
        convert_mock.assert_not_called()
        self.assertTrue(result.stop_result.succeeded)
        self.assertEqual(result.fetch_result.returncode, 1)
        self.assertIsNone(result.convert_result)
        self.assertEqual(result.settle_seconds, 1.0)
        self.assertIn("fetch failed", result.cleanup_error)

    def test_dry_run_does_not_sleep(self):
        with patch.object(camera_core, "stop_camera", return_value=_result(name="stop")), patch.object(
            camera_core.time, "sleep"
        ) as sleep_mock, patch.object(
            camera_core, "fetch_camera", return_value=_result(name="fetch")
        ), patch.object(camera_core, "convert_camera", return_value=_result(name="convert")):
            result = camera_core.stop_and_fetch_camera(
                self.system_config.camera,
                self.system_config.output_root,
                settle_seconds=3.0,
                dry_run=True,
            )

        sleep_mock.assert_not_called()
        self.assertEqual(result.settle_seconds, 3.0)
        self.assertTrue(result.convert_result.succeeded)
