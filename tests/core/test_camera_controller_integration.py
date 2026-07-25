from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest

import remote_camera_control
from rpi_visual_stimuli.core import camera as camera_core
from tests.helpers import load_repo_system_config


class CameraControllerIntegrationTests(unittest.TestCase):
    def setUp(self):
        system_config = load_repo_system_config()
        self.camera_config = replace(
            system_config.camera,
            host="pi@test-camera",
            remote_repo="/opt/camera_repo",
            remote_start="/opt/camera_repo/start_custom.py",
            remote_stop="/opt/camera_repo/stop_custom.sh",
            remote_video_root="/srv/camera_videos",
            framerate=47,
        )
        self.local_output_root = Path("/tmp/rpi_visual_stimuli_camera_out")
        self.parser = remote_camera_control.build_parser()

    def _parse_command(self, result: camera_core.CameraCommandResult):
        self.assertGreaterEqual(len(result.command), 3)
        return self.parser.parse_args(list(result.command[2:]))

    def test_preflight_command_parses_through_real_controller_parser(self):
        result = camera_core.preflight_camera(
            self.camera_config,
            self.local_output_root,
            dry_run=True,
        )
        args = self._parse_command(result)
        self.assertEqual(args.command, "preflight")
        self.assertEqual(args.camera_host, "pi@test-camera")
        self.assertEqual(args.remote_camera_repo, "/opt/camera_repo")
        self.assertEqual(args.remote_camera_start, "/opt/camera_repo/start_custom.py")
        self.assertEqual(args.remote_camera_stop, "/opt/camera_repo/stop_custom.sh")
        self.assertEqual(args.remote_video_root, "/srv/camera_videos")
        self.assertEqual(args.local_output_root, str(self.local_output_root))

    def test_start_command_parses_through_real_controller_parser(self):
        result = camera_core.start_camera(
            "mouse-7",
            "session-123_ABC",
            self.camera_config,
            self.local_output_root,
            dry_run=True,
        )
        args = self._parse_command(result)
        self.assertEqual(args.command, "start")
        self.assertEqual(args.mouse_id, "mouse-7")
        self.assertEqual(args.session_id, "session-123_ABC")
        self.assertEqual(args.framerate, 47)
        self.assertEqual(args.camera_host, "pi@test-camera")
        self.assertEqual(args.remote_camera_repo, "/opt/camera_repo")
        self.assertEqual(args.remote_camera_start, "/opt/camera_repo/start_custom.py")
        self.assertEqual(args.remote_camera_stop, "/opt/camera_repo/stop_custom.sh")
        self.assertEqual(args.remote_video_root, "/srv/camera_videos")
        self.assertEqual(args.local_output_root, str(self.local_output_root))

    def test_stop_command_parses_through_real_controller_parser(self):
        result = camera_core.stop_camera(
            self.camera_config,
            self.local_output_root,
            dry_run=True,
            ignore_errors=True,
        )
        args = self._parse_command(result)
        self.assertEqual(args.command, "stop")
        self.assertEqual(args.camera_host, "pi@test-camera")
        self.assertEqual(args.remote_camera_stop, "/opt/camera_repo/stop_custom.sh")
        self.assertEqual(args.remote_video_root, "/srv/camera_videos")
        self.assertEqual(args.local_output_root, str(self.local_output_root))

    def test_fetch_command_parses_through_real_controller_parser(self):
        result = camera_core.fetch_camera(
            self.camera_config,
            self.local_output_root,
            dry_run=True,
            keep_source_files=True,
            skip_conversion=True,
        )
        args = self._parse_command(result)
        self.assertEqual(args.command, "fetch")
        self.assertEqual(args.camera_host, "pi@test-camera")
        self.assertEqual(args.remote_video_root, "/srv/camera_videos")
        self.assertEqual(args.local_output_root, str(self.local_output_root))
        self.assertTrue(args.keep_source_files)
        self.assertTrue(args.skip_conversion)

    def test_convert_command_parses_through_real_controller_parser(self):
        result = camera_core.convert_camera(
            self.camera_config,
            self.local_output_root,
            dry_run=True,
        )
        args = self._parse_command(result)
        self.assertEqual(args.command, "convert")
        self.assertEqual(args.framerate, 47)
        self.assertEqual(args.local_output_root, str(self.local_output_root))

    def test_status_command_parses_through_real_controller_parser(self):
        result = camera_core.camera_status(
            self.camera_config,
            dry_run=True,
        )
        args = self._parse_command(result)
        self.assertEqual(args.command, "status")
        self.assertEqual(args.camera_host, "pi@test-camera")
        self.assertEqual(args.remote_camera_start, "/opt/camera_repo/start_custom.py")

    def test_unsupported_arguments_fail_for_wrong_subcommand(self):
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["stop", "--remote-repo", "/opt/camera_repo"])
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["convert", "--remote-stop", "/opt/camera_repo/stop_custom.sh"])
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["status", "--remote-repo", "/opt/camera_repo"])
