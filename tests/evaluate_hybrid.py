"""Opt-in live evaluation; isolated SQLite/files/Milvus/Neo4j, real model calls.

Run from the repository root: python -B -X utf8 -m tests.evaluate_hybrid
or python -B -X utf8 tests/evaluate_hybrid.py (root is added below).
"""
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.config import PROJECT_ROOT, config
from app.main import app
from app.repositories import workspace
from app.services import chat, documents, knowledge_graph, rag, index_jobs


def evaluate(output):
    fixture = json.loads(Path(__file__).with_name("hybrid_cases.json").read_text(encoding="utf-8"))
    run_id = "kb_eval_" + uuid4().hex[:12]
    output.mkdir(parents=True, exist_ok=True)
    config.database = output / "data" / "workspace.db"
    config.upload_dir = output / "uploads"
    config.milvus_collection_name = run_id
    config.graph_namespace = run_id
    config.neo4j_enabled = True
    config.warmup_on_start = False
    rag._store = None
    rag.invalidate_retrieval_cache()
    records = []
    report = {"run_id":run_id,"started_at":datetime.now(timezone.utc).isoformat(),
              "model":config.llm_model_name,"embedding":config.text_embeddings_model_path,
              "scoring":"关键词及实际引用文件覆盖校验；不等于人工评审准确率。", "cases":records}
    def save():
        (output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),encoding="utf-8")
    save()
    try:
        with TestClient(app) as client:
            task_ids = []
            for name, text in fixture["documents"].items():
                started = time.perf_counter()
                response = client.post("/api/index-jobs",files={"file":(name,text.encode())})
                response.raise_for_status()
                task_ids.append(response.json()["task_id"])
                print("queued", name, "in", round(time.perf_counter()-started,3), "s",flush=True)
            deadline = time.monotonic() + 1200
            while time.monotonic() < deadline:
                jobs = [workspace.job(i) for i in task_ids]
                if any(j["status"] == "failed" for j in jobs):
                    raise RuntimeError("索引任务失败：" + str([(j["name"],j["error"]) for j in jobs if j["status"] == "failed"]))
                if all(j["status"] == "succeeded" for j in jobs):
                    break
                time.sleep(1)
            else:
                raise RuntimeError("索引任务等待超时")
            report["jobs"] = jobs
            print("indexed",len(workspace.documents()),"documents",flush=True)
            for case in fixture["cases"]:
                for mode in ("vector", "hybrid"):
                    # Baseline reproduces the original independent vector-only question flow.
                    def vector_retrieve(question):
                        start = time.perf_counter()
                        sources = list(rag._retrieve_cached(question))
                        return sources, round((time.perf_counter()-start)*1000)
                    retrieve = rag.retrieve if mode == "hybrid" else vector_retrieve
                    rewrite = rag.rewrite_question if mode == "hybrid" else lambda q,h:q
                    with patch.object(rag,"retrieve",side_effect=retrieve),patch.object(rag,"rewrite_question",side_effect=rewrite):
                        sid = None
                        if case.get("setup"):
                            sid = chat.ask(case["setup"])["session_id"]
                        rag.invalidate_retrieval_cache()
                        started = time.perf_counter()
                        result = chat.ask(case["question"],sid)
                    answer = result["answer"]
                    correctness = all(word in answer for word in case.get("expected",[]))
                    correctness = correctness and not any(word in answer for word in case.get("reject",[]))
                    if case.get("expected_any"):
                        correctness = correctness and any(word in answer for word in case["expected_any"])
                    cited = set()
                    for number in re.findall(r"\[(\d+)\]",answer):
                        index = int(number)-1
                        if 0 <= index < len(result["sources"]):
                            cited.add(result["sources"][index]["name"])
                    coverage = set(case["sources"]).issubset(cited)
                    support = all(source["content"] in fixture["documents"].get(source["name"],"") for source in result["sources"])
                    record = {"id":case["id"],"mode":mode,"question":case["question"],
                        "expected":case.get("expected",case.get("expected_any")),"correct_rule":correctness,
                        "required_citations_covered":coverage,"source_text_verified":support,
                        "elapsed_ms":round((time.perf_counter()-started)*1000), **result}
                    records.append(record)
                    save()
                    print(case["id"],mode,"keywords",correctness,"citations",coverage,"ms",record["elapsed_ms"],flush=True)
            report["summary"] = {mode:{"count":len(rows),
                "correct_rule":sum(r["correct_rule"] for r in rows),
                "citation_coverage":sum(r["required_citations_covered"] for r in rows),
                "mean_ms":round(sum(r["elapsed_ms"] for r in rows)/len(rows))}
                for mode in ("vector","hybrid") for rows in [[r for r in records if r["mode"] == mode]]}
            # Exercise real SSE graph framing and original document access.
            response = client.post("/rag/chat/stream/",json={"question":"林然负责的项目使用什么数据库？"})
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            assert events[-1]["type"] == "done", events[-1]
            assert any(e["type"] == "graph" and e["graph"]["edges"] for e in events)
            source = events[-1]["sources"][0]
            assert client.get(f"/api/documents/{source['doc_id']}/original").status_code == 200
            # Remove a single document, verify no orphan evidence, then clear the isolated namespace.
            deleted = workspace.documents()[0]
            documents.remove(deleted["id"])
            assert not any(s["doc_id"] == deleted["id"] for s in knowledge_graph.search("林然天枢青岚周宁海隼墨石钱禾晨曦苏禾流萤"))
            assert client.get(f"/api/documents/{deleted['id']}/original").status_code == 404
            report["integration"] = {"sse_graph":True,"original":True,"delete":True}
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        index_jobs._executor.shutdown(wait=True)
        # Never use the user's live collection/namespace here.
        assert config.milvus_collection_name == run_id and config.graph_namespace == run_id
        cleanup_errors = []
        for cleanup in (rag.clear, knowledge_graph.clear):
            try:
                cleanup()
            except Exception as exc:
                cleanup_errors.append(type(exc).__name__)
        report["cleanup_errors"] = cleanup_errors
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        save()
    print(json.dumps(report["summary"],ensure_ascii=False),flush=True)


if __name__ == "__main__":
    evaluate(PROJECT_ROOT / "temp" / "sprint" / ("evaluation-" + datetime.now().strftime("%Y%m%d-%H%M%S")))
