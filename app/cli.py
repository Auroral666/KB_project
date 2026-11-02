"""Manage only this project's background server and verify HTTP readiness."""
import argparse
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import psutil

from app.config import PROJECT_ROOT, RUNTIME_DIR, config

RECORD = RUNTIME_DIR / "service.json"
BASE_URL = f"http://{config.fastapi_host}:{config.fastapi_port}"
LOCAL_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def managed_process():
    if not RECORD.exists():
        return None
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    try:
        process = psutil.Process(record["pid"])
        if abs(process.create_time() - record["created_at"]) > 0.01:
            return None  # A reused PID never grants permission to terminate another process.
        command = process.cmdline()
        owned = (Path(process.cwd()).resolve() == PROJECT_ROOT
                 and Path(process.exe()).resolve() == Path(record["python"]).resolve()
                 and any(command[i:i + 2] == ["-m", "app"] for i in range(len(command) - 1))
                 and Path(record["project"]).resolve() == PROJECT_ROOT)
        if not owned:
            raise RuntimeError("进程归属不匹配，未操作该进程。请检查 temp/runtime/service.json。")
        return process
    except psutil.NoSuchProcess:
        return None


def healthy():
    try:
        with LOCAL_HTTP.open(BASE_URL + "/health", timeout=1) as response:
            return response.status == 200 and json.load(response) == {
                "status": "ok", "application": "knowledge-studio"}
    except (OSError, ValueError, urllib.error.URLError):
        return False


def wait_ready(process):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if not process.is_running():
            break
        if healthy():
            return
        time.sleep(0.4)
    raise RuntimeError("服务未能就绪，请查看 temp/runtime/server-error.log。")


def start():
    print("========== 1. 检查运行环境 ==========")
    process = managed_process()
    if process is not None:
        wait_ready(process)
        print(f"项目已在运行：{BASE_URL}（未重复启动）")
        return
    missing = [name for name in ("uvicorn", "fastapi", "dotenv", "pymilvus", "sentence_transformers")
               if importlib.util.find_spec(name) is None]
    if missing:
        raise RuntimeError("当前 Python 环境缺少依赖：" + ", ".join(missing))
    if not (PROJECT_ROOT / ".env").is_file():
        raise RuntimeError("缺少 .env，请复制 .env.example 并填写本机配置。")
    with socket.socket() as probe:
        probe.settimeout(1)
        if probe.connect_ex((config.fastapi_host, config.fastapi_port)) == 0:
            raise RuntimeError(f"端口 {config.fastapi_port} 已被其他进程占用，未启动或停止其他项目。")
    print("========== 2. 启动并检查服务 ==========")
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with (RUNTIME_DIR / "server.log").open("ab") as stdout, (RUNTIME_DIR / "server-error.log").open("ab") as stderr:
        child = subprocess.Popen([sys.executable, "-B", "-X", "utf8", "-m", "app"],
            cwd=PROJECT_ROOT, stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    process = psutil.Process(child.pid)
    RECORD.write_text(json.dumps({"pid": child.pid, "created_at": process.create_time(),
        "project": str(PROJECT_ROOT), "python": sys.executable, "port": config.fastapi_port},
        ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        wait_ready(process)
    except Exception:
        if process.is_running():
            process.terminate()
            process.wait(10)
        raise
    print(f"启动成功：{BASE_URL}")
    print("模型将在后台预热；日志位于 temp/runtime。关闭此窗口后服务仍运行，双击“停止项目.cmd”停止。")


def stop():
    print("========== 1. 核实项目进程 ==========")
    process = managed_process()
    if process is None:
        print("项目已经停止。")
        return
    print("========== 2. 停止本项目服务 ==========")
    process.terminate()
    process.wait(10)
    print("项目已停止。")


def main():
    parser = argparse.ArgumentParser(description="知屿本地服务管理")
    parser.add_argument("action", choices=("start", "stop", "status"))
    action = parser.parse_args().action
    try:
        if action == "start":
            start()
        elif action == "stop":
            stop()
        else:
            running = managed_process() is not None and healthy()
            print(f"项目运行中：{BASE_URL}" if running else "项目未运行或尚未就绪。")
            return 0 if running else 1
    except (OSError, ValueError, RuntimeError, KeyError, psutil.Error) as exc:
        print(f"操作失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
