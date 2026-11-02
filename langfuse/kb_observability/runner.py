"""Start/stop an instrumented copy of the existing app without editing its sources."""
import argparse
import asyncio
import contextlib
import importlib.metadata
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import psutil

from app.config import PROJECT_ROOT, config
from kb_observability import tracing

FOLDER = Path(__file__).resolve().parents[1]
RUNTIME = FOLDER / "temp" / "runtime"
RECORD = RUNTIME / "service.json"
STOP = RUNTIME / "stop.request"
ENTRY = FOLDER / "run.py"
BASE = f"http://{config.fastapi_host}:{config.fastapi_port}"
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def managed_process():
    if not RECORD.exists():
        return None
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    try:
        process = psutil.Process(record["pid"])
        if abs(process.create_time() - record["created_at"]) > 0.01:
            return None
        command = process.cmdline()
        if Path(process.cwd()).resolve() != PROJECT_ROOT or str(ENTRY) not in command or "serve" not in command:
            raise RuntimeError("进程归属不匹配，未操作该进程。")
        if Path(process.exe()).resolve() != Path(record["python"]).resolve():
            raise RuntimeError("Python 进程与记录不匹配，未操作该进程。")
        return process
    except psutil.NoSuchProcess:
        return None


def status():
    with HTTP.open(BASE + "/api/langfuse/status", timeout=2) as response:
        return json.load(response)


def start():
    print("========== 1. 检查观测环境 ==========")
    if not (FOLDER / ".packages" / "langfuse" / "__init__.py").is_file():
        raise RuntimeError("缺少独立依赖，请先运行 langfuse/安装观测依赖.cmd。")
    existing = managed_process()
    if existing:
        status()
        print(f"观测版项目已在运行：{BASE}（未重复启动）")
        return
    # Reuse the existing ownership checks; never stop an unknown listener or a shared container.
    from app.cli import managed_process as original_process, stop as stop_original
    previous = original_process()
    if previous:
        print("已核实当前项目进程，正在切换到独立观测入口。")
        stop_original()
    import socket
    with socket.socket() as probe:
        probe.settimeout(1)
        if probe.connect_ex((config.fastapi_host, config.fastapi_port)) == 0:
            raise RuntimeError("项目端口已被其他进程占用，未操作该进程。")
    RUNTIME.mkdir(parents=True, exist_ok=True)
    STOP.unlink(missing_ok=True)
    with (RUNTIME / "server.log").open("ab") as stdout, (RUNTIME / "server-error.log").open("ab") as stderr:
        child = subprocess.Popen([sys.executable, "-B", "-X", "utf8", str(ENTRY), "serve"],
            cwd=PROJECT_ROOT, stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    process = psutil.Process(child.pid)
    RECORD.write_text(json.dumps({"pid": child.pid, "created_at": process.create_time(),
        "python": sys.executable, "project": str(PROJECT_ROOT)}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("========== 2. 启动并检查观测服务 ==========")
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and process.is_running():
        try:
            result = status()
            print(f"启动成功：{BASE}；Langfuse {'已启用' if result['enabled'] else '未启用'}。")
            print("云端连通性可运行“检查观测连接.cmd”；日志位于 langfuse/temp/runtime。")
            return
        except (OSError, ValueError):
            time.sleep(0.5)
    raise RuntimeError("服务尚未就绪，请检查 langfuse/temp/runtime/server-error.log。")


def stop():
    print("========== 1. 核实观测服务进程 ==========")
    process = managed_process()
    if process is None:
        print("观测服务已经停止。")
        return
    STOP.write_text("stop", encoding="utf-8")
    process.wait(40)
    print("观测服务已停止，并已执行观测数据刷新。")


async def serve():
    from kb_observability.instrumentation import install
    install()
    from app.main import app
    import uvicorn
    from fastapi.concurrency import run_in_threadpool

    original_lifespan = app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def lifespan(application):
        try:
            async with original_lifespan(application):
                yield
        finally:
            await run_in_threadpool(tracing.shutdown)

    app.router.lifespan_context = lifespan

    @app.get("/api/langfuse/status")
    def observation_status():
        return {"enabled": tracing.client() is not None, "sdk_version": importlib.metadata.version("langfuse"),
                "last_trace_id": tracing.last_trace_id, "mode": "runtime-instrumentation"}

    server = uvicorn.Server(uvicorn.Config(app, host=config.fastapi_host, port=config.fastapi_port, log_level="info"))

    async def watch_stop():
        while not server.should_exit:
            if STOP.exists():
                server.should_exit = True
                return
            await asyncio.sleep(0.3)

    watcher = asyncio.create_task(watch_stop())
    try:
        await server.serve()
    finally:
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher


def check():
    sdk = tracing.client()
    if sdk is None:
        raise RuntimeError("Langfuse 未启用，请检查独立配置与依赖。")
    try:
        connected = sdk.auth_check()
    except Exception as exc:
        raise RuntimeError(f"云端连接验证失败（{type(exc).__name__}），请核对独立配置与网络。") from None
    if not connected:
        raise RuntimeError("云端认证未通过，请核对项目密钥与所属区域。")
    print("Langfuse 项目认证通过：" + tracing.setting("LANGFUSE_BASE_URL"))
    tracing.shutdown()


def main():
    parser = argparse.ArgumentParser(description="知屿 Langfuse 独立观测入口")
    parser.add_argument("action", nargs="?", default="serve", choices=("start", "stop", "status", "check", "serve", "test"))
    action = parser.parse_args().action
    try:
        if action == "test":
            import unittest
            from kb_observability.instrumentation import install
            os.environ["LANGFUSE_ENABLED"] = "false"
            install()
            suite = unittest.TestSuite()
            loader = unittest.TestLoader()
            for folder in (FOLDER / "tests", PROJECT_ROOT / "tests"):
                suite.addTests(loader.discover(str(folder), pattern="test_*.py", top_level_dir=str(folder)))
            return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
        if action == "serve":
            asyncio.run(serve())
        elif action == "start":
            start()
        elif action == "stop":
            stop()
        elif action == "check":
            check()
        else:
            print(json.dumps(status(), ensure_ascii=False))
        return 0
    except (OSError, RuntimeError, ValueError, KeyError, psutil.Error) as exc:
        print("操作失败：" + str(exc), file=sys.stderr)
        return 1
