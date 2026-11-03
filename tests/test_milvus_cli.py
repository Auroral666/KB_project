"""Validate startup failures and ordering without changing the live shared database."""
import contextlib
import io
import subprocess
import unittest
from unittest.mock import patch

from app import milvus_cli as cli


def container(image, running=False, health="healthy"):
    return {"Config": {"Image": image}, "State": {"Running": running, "Health": {"Status": health}},
            "HostConfig": {"PortBindings": {"19530/tcp": [{"HostPort": "19530"}]}}}


class MilvusStartupTests(unittest.TestCase):
    def setUp(self):
        for name, value in (("milvus_host", "localhost"), ("milvus_port", "19530"),
                            ("milvus_etcd_container", "milvus-etcd"),
                            ("milvus_minio_container", "milvus-minio"),
                            ("milvus_container", "milvus-standalone")):
            patcher = patch.object(cli.config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        redirect = contextlib.redirect_stdout(io.StringIO())
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)

    def test_existing_service_needs_no_docker_or_restart(self):
        with patch.object(cli, "connected", return_value=True), \
                patch.object(cli, "ensure_docker") as ensure, patch.object(cli, "docker") as docker:
            cli.start()
        ensure.assert_not_called()
        docker.assert_not_called()

    def test_unreachable_remote_service_does_not_start_local_containers(self):
        with patch.object(cli.config, "milvus_host", "192.0.2.1"), \
                patch.object(cli, "connected", return_value=False), \
                patch.object(cli, "ensure_docker") as ensure:
            with self.assertRaisesRegex(RuntimeError, "远程 Milvus"):
                cli.start()
        ensure.assert_not_called()

    def launch_stack(self, running=False):
        events = []
        images = {"milvus-etcd": "quay.io/coreos/etcd:v3.5.25",
                  "milvus-minio": "minio/minio:RELEASE.2024-12-18T13-15-44Z",
                  "milvus-standalone": "milvusdb/milvus:v2.6.18"}

        def inspect(name):
            return container(images[name], running=running)

        with patch.object(cli, "connected", side_effect=[False, True]), \
                patch.object(cli, "ensure_docker"), \
                patch.object(cli, "inspect_container", side_effect=inspect), \
                patch.object(cli, "wait_container", side_effect=lambda name: events.append(("ready", name))), \
                patch.object(cli, "docker", side_effect=lambda *args: events.append(args)):
            cli.start()
        return events

    def test_stopped_dependencies_are_ready_before_milvus_starts(self):
        self.assertEqual(self.launch_stack(), [
            ("start", "milvus-etcd"), ("ready", "milvus-etcd"),
            ("start", "milvus-minio"), ("ready", "milvus-minio"),
            ("start", "milvus-standalone"), ("ready", "milvus-standalone"),
        ])

    def test_running_containers_are_not_restarted(self):
        self.assertEqual(self.launch_stack(running=True), [
            ("ready", "milvus-etcd"), ("ready", "milvus-minio"), ("ready", "milvus-standalone")])

    def test_missing_or_wrong_container_prevents_all_starts(self):
        for failure in (RuntimeError("缺少容器"), container("redis:7")):
            with self.subTest(failure=failure), \
                    patch.object(cli, "connected", return_value=False), \
                    patch.object(cli, "ensure_docker"), \
                    patch.object(cli, "inspect_container", side_effect=[
                        container("quay.io/coreos/etcd:3"), failure]), \
                    patch.object(cli, "docker") as docker:
                with self.assertRaises(RuntimeError):
                    cli.start()
                docker.assert_not_called()

    def test_mismatched_port_prevents_starting_wrong_database(self):
        with patch.object(cli.config, "milvus_port", "29530"), \
                patch.object(cli, "connected", return_value=False), \
                patch.object(cli, "ensure_docker"), \
                patch.object(cli, "inspect_container", side_effect=[
                    container("quay.io/coreos/etcd:3"), container("minio/minio:latest"),
                    container("milvusdb/milvus:2")]), patch.object(cli, "docker") as docker:
            with self.assertRaisesRegex(RuntimeError, "端口映射"):
                cli.start()
            docker.assert_not_called()

    def test_dependency_exit_prevents_starting_database(self):
        with patch.object(cli, "inspect_container", return_value=container("minio/minio:latest")):
            with self.assertRaisesRegex(RuntimeError, "已退出"):
                cli.wait_container("milvus-minio")

    def test_dependency_health_timeout_is_reported(self):
        with patch.object(cli, "inspect_container", return_value=container("minio/minio:latest", True, "starting")), \
                patch.object(cli.time, "monotonic", side_effect=[0, 1, 61]), \
                patch.object(cli.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "60 秒"):
                cli.wait_container("milvus-minio")

    def test_rpc_timeout_is_not_reported_as_success(self):
        with patch.object(cli, "connected", return_value=False), \
                patch.object(cli, "ensure_docker"), \
                patch.object(cli, "inspect_container", side_effect=[
                    container("quay.io/coreos/etcd:3", True), container("minio/minio:latest", True),
                    container("milvusdb/milvus:2", True)]), patch.object(cli, "wait_container"), \
                patch.object(cli.time, "monotonic", side_effect=[0, 1, 121]), \
                patch.object(cli.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "120 秒内连接成功"):
                cli.start()

    def test_docker_cli_missing_has_actionable_failure(self):
        with patch.object(cli.shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "安装 Docker Desktop"):
                cli.ensure_docker()

    @unittest.skipUnless(cli.os.name == "nt", "Docker Desktop auto-start is Windows-specific")
    def test_docker_desktop_is_started_when_engine_is_down(self):
        with patch.object(cli.shutil, "which", return_value="docker.exe"), \
                patch.object(cli.Path, "is_file", return_value=True), \
                patch.object(cli, "docker", side_effect=[RuntimeError("engine down"), "28.0"]), \
                patch.object(cli.subprocess, "Popen") as launch:
            cli.ensure_docker()
        launch.assert_called_once()
        self.assertEqual(cli.Path(launch.call_args.args[0][0]).name, "Docker Desktop.exe")

    @unittest.skipUnless(cli.os.name == "nt", "Docker Desktop auto-start is Windows-specific")
    def test_docker_desktop_timeout_is_reported(self):
        with patch.object(cli.shutil, "which", return_value="docker.exe"), \
                patch.object(cli.Path, "is_file", return_value=True), \
                patch.object(cli, "docker", side_effect=RuntimeError("engine down")), \
                patch.object(cli.subprocess, "Popen"), \
                patch.object(cli.time, "monotonic", side_effect=[0, 1, 121]), \
                patch.object(cli.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "120 秒内就绪"):
                cli.ensure_docker()

    def test_main_returns_failure_for_docker_timeout(self):
        with patch.object(cli, "start", side_effect=subprocess.TimeoutExpired("docker", 15)), \
                contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(cli.main(), 1)
        self.assertIn("向量服务启动失败", errors.getvalue())

    def test_probe_disconnects_after_failed_rpc(self):
        with patch("pymilvus.connections.connect"), \
                patch("pymilvus.utility.get_server_version", side_effect=RuntimeError("not ready")), \
                patch("pymilvus.connections.disconnect") as disconnect:
            self.assertFalse(cli.connected())
        disconnect.assert_called_once_with("kb_startup_probe")


if __name__ == "__main__":
    unittest.main()
