"""Start this project's Docker graph service and wait for Bolt connectivity."""
import subprocess
import time

from app.config import PROJECT_ROOT, config
from app.services import knowledge_graph


def start():
    if not config.neo4j_enabled:
        print("Neo4j 已通过配置关闭，使用向量检索。")
        return
    if not config.neo4j_password:
        raise RuntimeError("请先在 .env 配置 neo4j_password。")
    print("========== 2. 启动项目 Neo4j 容器 ==========", flush=True)
    subprocess.run(["docker", "compose", "-p", "kb-project", "-f", "compose.neo4j.yml", "up", "-d"],
                   cwd=PROJECT_ROOT, check=True, timeout=600)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if knowledge_graph.status()["connected"]:
            print("Neo4j 已就绪：http://127.0.0.1:7474", flush=True)
            return
        time.sleep(1)
    raise RuntimeError("Neo4j 未在90秒内就绪，请检查 docker compose 日志。")


if __name__ == "__main__":
    try:
        start()
    except Exception as exc:
        print(f"Neo4j 启动失败：{type(exc).__name__}：{exc}")
        raise SystemExit(1)
