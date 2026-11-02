"""Behavioral regression for jobs, grounding, memory and retrieval isolation."""
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.documents import Document

from app.config import config
from app.main import app
from app.repositories import workspace
from app.services import chat, documents, index_jobs, knowledge_graph as graph, rag
from app.services.document_parser import load_semantic_chunks


class HybridTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = [patch.object(config, "database", Path(self.temp.name) / "data" / "test.db"),
            patch.object(config, "upload_dir", Path(self.temp.name) / "uploads"),
            patch.object(config, "warmup_on_start", False), patch.object(config, "neo4j_enabled", True)]
        for p in self.patches:
            p.start()
        workspace.initialize()
        self.source = {"doc_id": "a"*32, "name": "甲.txt", "chunk": 1, "page": 0, "content": "林然负责天枢。"}

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()
        rag.invalidate_retrieval_cache()

    def test_semantic_boundaries_preserve_pages_tail_and_long_sentences(self):
        docs = [Document(page_content="同类一。同类二。异类三。", metadata={"page": 2}),
                Document(page_content="x" * 1200 + "终点", metadata={"page": 3})]
        embed = SimpleNamespace(embed_documents=lambda units: [[1,0], [1,0], [0,1]] if len(units) == 3 and units[0] == "同类一。" else [[1,0]]*len(units))
        with patch("app.services.document_parser.load_documents", return_value=docs):
            chunks = load_semantic_chunks(None, embed)
        self.assertEqual(chunks[0].page_content, "同类一。同类二。")
        self.assertEqual(chunks[1].page_content, "异类三。")
        self.assertEqual("".join(d.page_content for d in chunks), "".join(d.page_content for d in docs))
        self.assertTrue(all(len(d.page_content) <= 512 for d in chunks))
        self.assertEqual(chunks[-1].metadata["page"], 3)

    def test_extraction_rejects_fabricated_evidence_and_accepts_literal_support(self):
        fact = {"subject":"林然","predicate":"负责","object":"天枢","evidence":"林然负责天枢。"}
        with patch.object(rag, "get_llm") as llm:
            llm.return_value.invoke.return_value.content = json.dumps({"triples":[fact]}, ensure_ascii=False)
            self.assertEqual(graph.extract([Document(page_content="林然负责天枢。")])[0]["chunk"], 1)
            fact["evidence"] = "林然负责不存在的项目。"
            llm.return_value.invoke.return_value.content = json.dumps({"triples":[fact]}, ensure_ascii=False)
            with self.assertRaisesRegex(ValueError, "逐字依据"):
                graph.extract([Document(page_content="林然负责天枢。")])

    def test_background_upload_returns_before_worker_and_failure_is_durable(self):
        with TestClient(app) as client, patch.object(index_jobs._executor, "submit") as submit:
            response = client.post("/api/index-jobs", files={"file":("note.txt", "资料".encode())})
            self.assertEqual(response.status_code, 202)
            job_id = response.json()["task_id"]
            self.assertEqual(workspace.job(job_id)["status"], "queued")
            self.assertEqual(workspace.documents(), [])
            submit.assert_called_once()
            self.assertEqual(client.post("/rag/clear/").status_code, 409)
            with patch.object(rag, "semantic_chunks", side_effect=ValueError("无可提取文字")):
                index_jobs.process(job_id)
            job = client.get("/api/index-jobs/" + job_id).json()["job"]
            self.assertEqual(job["status"], "failed")
            self.assertIn("无可提取文字", job["error"])
            self.assertEqual(list(config.upload_dir.iterdir()), [])
            self.assertEqual(client.get("/api/index-jobs/missing").status_code, 404)

    def test_index_success_and_graph_failure_roll_back_both_stores(self):
        chunks = [Document(page_content="林然负责天枢。")]
        with patch.object(rag, "semantic_chunks", return_value=chunks), patch.object(graph, "extract", return_value=[]), \
             patch.object(rag, "add_chunks"), patch.object(rag, "delete_chunks") as vector_delete, \
             patch.object(graph, "write", side_effect=RuntimeError("graph offline")), patch.object(graph, "remove") as graph_delete:
            with self.assertRaises(RuntimeError):
                documents.create("a.txt", io.BytesIO(b"text"))
            self.assertEqual(workspace.documents(), [])
            self.assertEqual(list(config.upload_dir.iterdir()), [])
            self.assertEqual(vector_delete.call_count, 1)
            self.assertEqual(graph_delete.call_count, 1)
        with patch.object(rag, "semantic_chunks", return_value=chunks), patch.object(graph, "extract", return_value=[]), \
             patch.object(rag, "add_chunks"), patch.object(graph, "write"):
            doc = documents.create("a.txt", io.BytesIO(b"text"))
        with patch.object(graph, "remove") as remove_graph, patch.object(rag, "delete_chunks") as remove_vectors:
            documents.remove(doc["id"])
        remove_graph.assert_called_once_with(doc["id"])
        remove_vectors.assert_called_once_with(doc["id"])
        self.assertEqual(workspace.documents(), [])

    def test_recovery_does_not_duplicate_committed_document(self):
        workspace.add_document("a"*32,"a.txt",".txt",1,1)
        workspace.add_job("b"*32,"a"*32,"a.txt",".txt",1)
        workspace.update_job("b"*32,"running","writing_graph")
        with patch.object(index_jobs._executor, "submit") as submit:
            index_jobs.recover()
            submit.assert_not_called()
        self.assertEqual(workspace.job("b"*32)["status"],"succeeded")

    def test_restart_replaces_partial_writes_before_publishing(self):
        workspace.add_job("b"*32,"a"*32,"a.txt",".txt",4)
        workspace.update_job("b"*32,"running","writing_graph")
        (config.upload_dir/("a"*32+".txt")).write_bytes(b"text")
        events = []
        with patch.object(rag,"semantic_chunks",return_value=[Document(page_content="text")]), \
             patch.object(graph,"extract",return_value=[]), \
             patch.object(graph,"remove",side_effect=lambda d:events.append("remove_graph")), \
             patch.object(rag,"delete_chunks",side_effect=lambda d:events.append("remove_vector")), \
             patch.object(rag,"add_chunks",side_effect=lambda *a:events.append("write_vector")), \
             patch.object(graph,"write",side_effect=lambda *a:events.append("write_graph")):
            index_jobs.process("b"*32)
        self.assertEqual(events,["remove_graph","remove_vector","write_vector","write_graph"])
        self.assertEqual(workspace.job("b"*32)["status"],"succeeded")
        self.assertEqual(len(workspace.documents()),1)

    def test_history_window_rewrites_followup_and_keeps_original_question(self):
        sid = None
        for i in range(6):
            sid, _ = workspace.save_message(sid, f"问题{i}", f"回答{i}",[self.source],"answered",1,1)
        recent = workspace.recent_history(sid, 2)
        self.assertEqual([m["question"] for m in recent],["问题4","问题5"])
        with patch.object(rag,"get_llm") as llm:
            llm.return_value.invoke.return_value.content="天枢使用什么数据库？"
            self.assertEqual(rag.rewrite_question("它呢？", recent),"天枢使用什么数据库？")
        workspace.add_document(self.source["doc_id"],"甲.txt",".txt",1,1)
        with patch.object(rag,"rewrite_question",return_value="天枢使用什么数据库？") as rewrite, \
             patch.object(rag,"retrieve",return_value=([self.source],2)) as retrieve, \
             patch.object(rag,"answer",return_value="Neo4j [1]"):
            chat.ask("它呢？",sid)
        retrieve.assert_called_once_with("天枢使用什么数据库？")
        self.assertEqual(len(rewrite.call_args.args[1]),config.history_turns)
        self.assertEqual(workspace.history(sid)[-1]["question"],"它呢？")

    def test_parallel_routes_fuse_deduplicate_and_filter_deleted_sources(self):
        workspace.add_document(self.source["doc_id"],"甲.txt",".txt",1,1)
        barrier = threading.Barrier(2)
        related = {**self.source,"relations":[{"id":"r","from":"林然","to":"天枢","subject":"林然","object":"天枢","label":"负责"}]}
        deleted = {**self.source,"doc_id":"b"*32}
        def vector(q):
            barrier.wait(timeout=3)
            return [self.source,deleted]
        def graph_route(q):
            barrier.wait(timeout=3)
            return [related]
        with patch.object(rag,"_retrieve_cached",side_effect=vector),patch.object(graph,"search",side_effect=graph_route):
            sources, _ = rag.retrieve("林然")
        self.assertEqual(len(sources),1)
        self.assertEqual(len(sources[0]["relations"]),1)
        view = graph.from_sources(sources)
        self.assertEqual(len(view["nodes"]),2)
        self.assertEqual(view["edges"][0]["sources"][0]["doc_id"],self.source["doc_id"])

    def test_route_failure_degrades_and_total_failure_raises(self):
        workspace.add_document(self.source["doc_id"],"甲.txt",".txt",1,1)
        with patch.object(rag,"_retrieve_cached",return_value=[self.source]), \
             patch.object(graph,"search",side_effect=RuntimeError("offline")):
            sources, _ = rag.retrieve("林然")
        self.assertIn("retrieval_warning",sources[0])
        with patch.object(rag,"_retrieve_cached",side_effect=RuntimeError("offline")), \
             patch.object(graph,"search",side_effect=RuntimeError("offline")):
            with self.assertRaises(RuntimeError):
                rag.retrieve("林然")

    def test_sse_graph_and_history_share_same_evidence(self):
        workspace.add_document(self.source["doc_id"],"甲.txt",".txt",1,1)
        related = {**self.source,"relations":[{"id":"r","from":"a","to":"b","subject":"林然","object":"天枢","label":"负责"}]}
        with patch.object(rag,"retrieve",return_value=([related],3)), \
             patch.object(rag,"stream_answer",return_value=iter(["天枢 [1]"])):
            events = list(chat.stream("林然负责什么？"))
        self.assertEqual(events[2]["type"],"graph")
        self.assertEqual(events[2]["graph"], events[-1]["graph"])
        saved = workspace.history(events[-1]["session_id"])[0]
        self.assertEqual(graph.from_sources(saved["sources"]),events[-1]["graph"])


if __name__ == "__main__":
    unittest.main()
