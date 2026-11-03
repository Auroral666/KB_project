"""Exercise both launch modes without stopping live processes or shared services."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import psutil

from app import cli


class ProjectLifecycleTests(unittest.TestCase):
    def setUp(self):
        temp_root = cli.PROJECT_ROOT / "temp"
        temp_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.record = root / "service.json"
        self.observation_runtime = root / "observation"
        self.observation_runtime.mkdir()
        self.observation_record = self.observation_runtime / "service.json"
        for name, value in (("RECORD", self.record),
                            ("OBSERVATION_RUNTIME", self.observation_runtime),
                            ("OBSERVATION_RECORD", self.observation_record)):
            patcher = patch.object(cli, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.output = io.StringIO()
        redirect = contextlib.redirect_stdout(self.output)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)

    def recorded_process(self, observation=False):
        record_path = self.observation_record if observation else self.record
        record_path.write_text(json.dumps({
            "pid": 12345, "created_at": 100.0, "project": str(cli.PROJECT_ROOT),
            "python": str(Path(cli.sys.executable).resolve()),
        }), encoding="utf-8")
        process = Mock()
        process.create_time.return_value = 100.0
        process.cwd.return_value = str(cli.PROJECT_ROOT)
        process.exe.return_value = cli.sys.executable
        entry = [str(cli.OBSERVATION_ENTRY), "serve"] if observation else ["-m", "app"]
        process.cmdline.return_value = [cli.sys.executable, "-B", "-X", "utf8", *entry]
        return process

    def test_recognizes_normal_and_observation_records(self):
        for observation in (False, True):
            with self.subTest(observation=observation):
                process = self.recorded_process(observation)
                path = self.observation_record if observation else self.record
                with patch.object(cli.psutil, "Process", return_value=process):
                    self.assertIs(cli.managed_process(path), process)

    def test_reused_pid_does_not_grant_ownership(self):
        process = self.recorded_process(True)
        process.create_time.return_value = 200.0
        with patch.object(cli.psutil, "Process", return_value=process):
            self.assertIsNone(cli.managed_process(self.observation_record))
        process.cmdline.assert_not_called()

    def test_missing_process_is_treated_as_stopped(self):
        self.recorded_process(True)
        with patch.object(cli.psutil, "Process", side_effect=psutil.NoSuchProcess(12345)):
            self.assertIsNone(cli.managed_process(self.observation_record))

    def test_rejects_other_project_python_or_entry(self):
        for observation in (False, True):
            for field in ("cwd", "exe", "cmdline"):
                with self.subTest(observation=observation, field=field):
                    process = self.recorded_process(observation)
                    getattr(process, field).return_value = (
                        [cli.sys.executable, str(cli.OBSERVATION_ENTRY), "check"]
                        if field == "cmdline" else str(Path(self.temp.name) / "other")
                    )
                    path = self.observation_record if observation else self.record
                    with patch.object(cli.psutil, "Process", return_value=process):
                        with self.assertRaisesRegex(RuntimeError, "归属不匹配"):
                            cli.managed_process(path)
                    process.terminate.assert_not_called()

    def test_normal_start_reuses_observation_instance(self):
        process = self.recorded_process(True)
        with patch.object(cli.psutil, "Process", return_value=process), \
                patch.object(cli, "wait_ready") as ready, \
                patch.object(cli.subprocess, "Popen") as launch:
            cli.start()
        ready.assert_called_once_with(process)
        launch.assert_not_called()
        self.assertIn("Langfuse 观测版", self.output.getvalue())

    def test_status_recognizes_observation_instance(self):
        process = self.recorded_process(True)
        with patch.object(cli.psutil, "Process", return_value=process), \
                patch.object(cli, "healthy", return_value=True), \
                patch.object(cli.sys, "argv", ["cli", "status"]):
            self.assertEqual(cli.main(), 0)

    def test_stop_observation_requests_flush_and_removes_record(self):
        process = self.recorded_process(True)
        with patch.object(cli.psutil, "Process", return_value=process), \
                patch.object(cli, "port_in_use", return_value=False):
            cli.stop()
            cli.stop()
        self.assertEqual((self.observation_runtime / "stop.request").read_text(), "stop")
        process.wait.assert_called_once_with(40)
        process.terminate.assert_not_called()
        self.assertFalse(self.observation_record.exists())
        self.assertIn("项目已经停止", self.output.getvalue())

    def test_observation_timeout_terminates_only_verified_process(self):
        process = self.recorded_process(True)
        process.wait.side_effect = [psutil.TimeoutExpired(40, pid=12345), 0]
        with patch.object(cli.psutil, "Process", return_value=process), \
                patch.object(cli, "port_in_use", return_value=False):
            cli.stop()
        process.terminate.assert_called_once_with()
        self.assertEqual([call.args for call in process.wait.call_args_list], [(40,), (10,)])
        self.assertIn("可能未刷新", self.output.getvalue())

    def test_stop_normal_instance_waits_and_removes_record(self):
        process = self.recorded_process()
        with patch.object(cli.psutil, "Process", return_value=process), \
                patch.object(cli, "port_in_use", return_value=False):
            cli.stop()
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(10)
        self.assertFalse(self.record.exists())

    def test_stop_handles_both_records(self):
        normal = self.recorded_process()
        observation = self.recorded_process(True)
        with patch.object(cli.psutil, "Process", side_effect=[normal, observation]), \
                patch.object(cli, "port_in_use", return_value=False):
            cli.stop()
        normal.terminate.assert_called_once_with()
        observation.wait.assert_called_once_with(40)
        self.assertFalse(self.record.exists())
        self.assertFalse(self.observation_record.exists())

    def test_unknown_listener_cannot_be_reported_as_stopped(self):
        with patch.object(cli, "port_in_use", return_value=True), \
                patch.object(cli.sys, "argv", ["cli", "stop"]), \
                contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(cli.main(), 1)
        self.assertIn("仍被占用", errors.getvalue())
        self.assertNotIn("项目已经停止", self.output.getvalue())

    def test_failed_termination_keeps_record_and_returns_failure(self):
        process = self.recorded_process(True)
        process.wait.side_effect = psutil.TimeoutExpired(40, pid=12345)
        with patch.object(cli.psutil, "Process", return_value=process), \
                patch.object(cli.sys, "argv", ["cli", "stop"]), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(), 1)
        self.assertTrue(self.observation_record.exists())


if __name__ == "__main__":
    unittest.main()
