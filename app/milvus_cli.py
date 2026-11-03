"""Resume the existing local Milvus stack without recreating containers or data."""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from app.config import config


def docker(*args):
    result = subprocess.run(["docker", *args], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=15)
    if result.returncode:
        raise RuntimeError(f"docker {' '.join(args)} 失败：{result.stderr.strip()}")
    return result.stdout


def ensure_docker():
    if not shutil.which("docker"):
        raise RuntimeError("未找到 docker，请先安装 Docker Desktop。")
    try:
        docker("info", "--format", "{{.ServerVersion}}")
        return
    except (RuntimeError, subprocess.TimeoutExpired):
        pass
    desktop = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker/Docker/Docker Desktop.exe"
    if os.name != "nt" or not desktop.is_file():
        raise RuntimeError("Docker 引擎未运行，请启动 Docker 后重试。")
    print("正在启动 Docker Desktop，最多等待 120 秒……", flush=True)
    subprocess.Popen([str(desktop)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            docker("info", "--format", "{{.ServerVersion}}")
            return
        except (RuntimeError, subprocess.TimeoutExpired):
            time.sleep(2)
    raise RuntimeError("Docker Desktop 未能在 120 秒内就绪，请检查 Docker Desktop。")


def inspect_container(name):
    try:
        return json.loads(docker("inspect", name))[0]
    except RuntimeError as exc:
        raise RuntimeError(f"无法读取已有容器 {name}，请检查容器名称和 Docker 状态；"
                           "本入口不会新建或重建 Milvus 数据库。") from exc


def wait_container(name):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        state = inspect_container(name)["State"]
        if not state["Running"]:
            raise RuntimeError(f"容器 {name} 已退出，请查看 docker logs {name}。")
        if state.get("Health", {}).get("Status", "healthy") == "healthy":
            return
        time.sleep(1)
    raise RuntimeError(f"容器 {name} 未在 60 秒内健康，请查看 docker logs {name}。")


def connected():
    # A real RPC confirms Milvus readiness; an open TCP port alone is insufficient.
    from pymilvus import connections, utility
    alias = "kb_startup_probe"
    try:
        connections.connect(alias=alias, host=config.milvus_host, port=config.milvus_port, timeout=3)
        utility.get_server_version(using=alias, timeout=3)
        return True
    except Exception:
        return False
    finally:
        connections.disconnect(alias)


def start():
    print("========== 1. 检查并启动 Milvus 向量服务 ==========", flush=True)
    if connected():
        print(f"Milvus 已就绪：{config.milvus_host}:{config.milvus_port}（复用现有服务）", flush=True)
        return
    if config.milvus_host.lower().strip("[]") not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("远程 Milvus 无法连接，请在远程服务器启动服务并检查 .env；未操作本地容器。")
    ensure_docker()
    containers = [
        (config.milvus_etcd_container, "quay.io/coreos/etcd"),
        (config.milvus_minio_container, "minio/minio"),
        (config.milvus_container, "milvusdb/milvus"),
    ]
    # Validate every target before starting any container; preserve existing mounts.
    existing = []
    for name, repository in containers:
        container = inspect_container(name)
        if container["Config"]["Image"].split(":")[0] != repository:
            raise RuntimeError(f"容器 {name} 的镜像与预期 {repository} 不匹配，请检查配置。")
        if repository == "milvusdb/milvus":
            ports = container["HostConfig"].get("PortBindings") or {}
            if not any(p["HostPort"] == str(config.milvus_port) for p in ports.get("19530/tcp", []) or []):
                raise RuntimeError(f"容器 {name} 的端口映射与 milvus_port={config.milvus_port} 不匹配。")
        existing.append((name, container["State"]["Running"]))
    for name, running in existing:
        if not running:
            print(f"正在启动已有容器：{name}", flush=True)
            docker("start", name)
        wait_container(name)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if connected():
            print(f"Milvus 向量服务已就绪：{config.milvus_host}:{config.milvus_port}", flush=True)
            return
        time.sleep(1)
    raise RuntimeError(f"Milvus 未在 120 秒内连接成功，请检查 .env 和 docker logs {config.milvus_container}。")


def main():
    try:
        start()
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as exc:
        print(f"向量服务启动失败：{exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
