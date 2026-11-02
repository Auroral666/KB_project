"""Behavior checks use temporary files and never touch the live vector database."""
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import config
from app.services.document_parser import load_chunks
from app.main import app
from app.repositories import workspace as storage


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.graph_config = patch.object(config, "neo4j_enabled", False)
        self.graph_config.start()
        self.semantic_mock = patch("app.services.rag.semantic_chunks", side_effect=load_chunks)
        self.semantic_mock.start()
        self.rewrite_mock = patch("app.services.rag.rewrite_question", side_effect=lambda q, h: q)
        self.rewrite_mock.start()
        self.temp = tempfile.TemporaryDirectory()
        self.old_database, self.old_upload = config.database, config.upload_dir
        config.database = Path(self.temp.name) / "data" / "test.db"
        config.upload_dir = Path(self.temp.name) / "uploads"
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        config.database, config.upload_dir = self.old_database, self.old_upload
        self.temp.cleanup()
        self.graph_config.stop()
        self.semantic_mock.stop()
        self.rewrite_mock.stop()

    def upload(self, name="notes.txt", content=b"Knowledge Studio document. Tail preserved."):
        with patch("app.services.rag.add_chunks") as add:
            response = self.client.post("/rag/create/", files={"file": (name, content)})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(add.called)
        return response.json()["document"]

    def test_pages_have_navigation_and_no_teaching_route(self):
        for url in ("/", "/chat", "/knowledge", "/insights"):
            result = self.client.get(url)
            self.assertEqual(result.status_code, 200)
            self.assertIn("知屿", result.text)
            self.assertNotIn("面试与学习", result.text)
        self.assertEqual(self.client.get("/guide").status_code, 404)

    def test_upload_download_and_delete_are_consistent(self):
        doc = self.upload()
        overview = self.client.get("/api/overview").json()["summary"]
        self.assertEqual(overview["documents"], 1)
        self.assertGreater(overview["chunks"], 0)
        self.assertEqual(self.client.get(f"/api/documents/{doc['id']}/download").content,
                         b"Knowledge Studio document. Tail preserved.")
        with patch("app.services.rag.delete_chunks") as delete:
            result = self.client.delete(f"/api/documents/{doc['id']}")
            self.assertEqual(result.status_code, 200)
            delete.assert_called_once_with(doc["id"])
        self.assertEqual(storage.documents(), [])
        self.assertEqual(self.client.get(f"/api/documents/{doc['id']}/download").status_code, 404)

    def test_filename_cannot_escape_upload_folder(self):
        doc = self.upload("../../outside.txt")
        self.assertEqual(doc["name"], "outside.txt")
        self.assertEqual(len(list(config.upload_dir.iterdir())), 1)
        self.assertTrue((config.upload_dir / (doc["id"] + ".txt")).is_file())
        self.assertFalse((Path(self.temp.name) / "outside.txt").exists())

    def test_original_text_contains_unretrieved_surrounding_content(self):
        content = "文档开头，未参与检索。\n\n引用文字：金额为1750元。\n\n文档末尾也应保留。".encode()
        doc = self.upload(content=content)
        result = self.client.get(f"/api/documents/{doc['id']}/original")
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json()["pages"][0]["text"],content.decode())
        self.assertEqual(self.client.get("/api/documents/not-a-document/original").status_code,404)

    def test_original_pdf_serves_the_actual_file(self):
        doc_id = "a"*32
        raw = b"%PDF-1.4\noriginal bytes"
        (config.upload_dir/(doc_id+".pdf")).write_bytes(raw)
        storage.add_document(doc_id,"Original.pdf",".pdf",len(raw),1)
        response = self.client.get(f"/api/documents/{doc_id}/original")
        self.assertEqual(response.status_code,200)
        self.assertIn("application/pdf",response.headers["content-type"])
        self.assertEqual(response.content,raw)
        (config.upload_dir/(doc_id+".pdf")).unlink()
        self.assertEqual(self.client.get(f"/api/documents/{doc_id}/original").status_code,404)

    def test_pdf_viewer_module_uses_executable_mime_type(self):
        response = self.client.get("/static/vendor/pdfjs/build/pdf.mjs")
        self.assertEqual(response.status_code,200)
        self.assertIn("application/javascript",response.headers["content-type"])

    def test_rejects_invalid_uploads_and_rolls_back(self):
        self.assertEqual(self.client.post("/rag/create/", files={"file": ("bad.exe", b"text")}).status_code, 400)
        with patch("app.services.rag.delete_chunks"):
            self.assertEqual(self.client.post("/rag/create/", files={"file": ("empty.txt", b"")}).status_code, 400)
            with patch("app.services.rag.add_chunks", side_effect=RuntimeError("index unavailable")):
                self.assertEqual(self.client.post("/rag/create/", files={"file": ("note.txt", b"text")}).status_code, 503)
        self.assertEqual(storage.documents(), [])
        self.assertEqual(list(config.upload_dir.iterdir()), [])

    def test_upload_size_limit(self):
        with patch.object(config, "max_upload_bytes", 5), patch("app.services.rag.delete_chunks"):
            response = self.client.post("/rag/create/", files={"file": ("large.txt", b"123456")})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(list(config.upload_dir.iterdir()), [])

    def test_text_splitting_preserves_tail_and_long_unbroken_text(self):
        path = Path(self.temp.name) / "long.txt"
        path.write_text("开始。" * 400 + "x" * 1300 + "末尾不能丢失", encoding="utf-8")
        chunks = load_chunks(path)
        self.assertGreater(len(chunks), 3)
        self.assertTrue(chunks[-1].page_content.endswith("末尾不能丢失"))
        self.assertTrue(all(len(chunk.page_content) <= 512 for chunk in chunks))

    def test_question_sources_history_and_real_metrics(self):
        doc = self.upload()
        sources = [{"name":doc["name"], "doc_id":doc["id"], "chunk":1,"page":0,"distance":0.2,"content":"Evidence"}]
        with patch("app.services.rag.retrieve", return_value=(sources, 123)), patch("app.services.rag.answer", return_value="Answer [1]"):
            result = self.client.post("/rag/chat/", json={"question":"First question"}).json()
            self.assertEqual(result["sources"], sources)
            second = self.client.post("/rag/chat/", json={"question":"Second question","session_id":result["session_id"]})
            self.assertEqual(second.status_code, 200)
        history = self.client.get(f"/api/sessions/{result['session_id']}").json()["messages"]
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["sources"], sources)
        stats = self.client.get("/api/overview").json()
        self.assertEqual(stats["summary"]["questions"], 2)
        self.assertEqual(stats["summary"]["with_sources"], 2)
        self.assertEqual(sum(d["questions"] for d in stats["trend"]), 2)
        self.assertEqual(len(self.client.get("/api/overview?days=30").json()["trend"]), 30)

    def test_empty_knowledge_does_not_call_model(self):
        with patch("app.services.rag.retrieve") as retrieve:
            response = self.client.post("/rag/chat/", json={"question":"Hello"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "no_context")
        self.assertEqual(response.json()["sources"], [])
        retrieve.assert_not_called()

    def test_failed_chat_does_not_fabricate_metrics(self):
        self.upload()
        with patch("app.services.rag.retrieve", side_effect=RuntimeError("offline")):
            result = self.client.post("/rag/chat/", json={"question":"Hello"})
        self.assertEqual(result.status_code, 503)
        self.assertEqual(storage.overview()["summary"]["questions"], 0)

    def test_clear_is_fixed_to_project_collection(self):
        self.upload()
        with patch("app.services.rag.clear") as clear:
            result = self.client.post("/rag/clear/?collection_name=knowledge_collection")
            self.assertEqual(result.status_code, 200)
            clear.assert_called_once_with()
        self.assertEqual(config.milvus_collection_name, "kb_project_knowledge")
        self.assertEqual(storage.documents(), [])
        self.assertEqual(list(config.upload_dir.iterdir()), [])

    def test_input_and_cross_origin_validation(self):
        self.assertEqual(self.client.post("/rag/chat/", json={"question":" "}).status_code, 400)
        self.assertEqual(self.client.post("/rag/chat/", json={"question":"Hi","session_id":"../bad"}).status_code, 422)
        self.assertEqual(self.client.post("/rag/clear/", headers={"Origin":"https://outside.example"}).status_code, 403)

    def stream_events(self, question="First question"):
        response = self.client.post("/rag/chat/stream/", json={"question":question})
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]

    def test_stream_sends_deltas_and_saves_only_complete_answer(self):
        doc = self.upload()
        sources = [{"name":doc["name"], "doc_id":doc["id"], "chunk":1,"page":0,"distance":0.2,"content":"Evidence"}]
        def generate(question, context):
            yield "## 结论\n\n"
            self.assertEqual(storage.overview()["summary"]["questions"], 0)
            yield "准确回答 [1]"
        with patch("app.services.rag.retrieve", return_value=(sources, 12)), patch("app.services.rag.stream_answer", side_effect=generate):
            events = self.stream_events()
        self.assertEqual([e["type"] for e in events], ["status","sources","graph","delta","delta","done"])
        final = events[-1]
        self.assertEqual(final["answer"], "## 结论\n\n准确回答 [1]")
        self.assertIsInstance(final["first_token_ms"], int)
        history = storage.history(final["session_id"])
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["answer"], final["answer"])
        self.assertEqual(history[0]["first_token_ms"], final["first_token_ms"])

    def test_stream_failure_keeps_partial_answer_out_of_history(self):
        def interrupted(question, sources):
            yield "An incomplete answer"
            raise RuntimeError("Model connection failed")
        with patch("app.services.rag.stream_answer", side_effect=interrupted):
            events = self.stream_events()
        self.assertEqual(events[-1]["type"], "error")
        self.assertNotIn("done", [event["type"] for event in events])
        self.assertEqual(storage.sessions(), [])
        self.assertEqual(storage.overview()["summary"]["questions"], 0)

    def test_stream_without_documents_and_question_validation(self):
        events = self.stream_events()
        self.assertEqual(events[-1]["status"], "no_context")
        self.assertEqual(events[-1]["sources"], [])
        self.assertEqual(self.client.post("/rag/chat/stream/", json={"question":" "}).status_code, 400)

    def test_retrieval_cache_invalidation(self):
        from app.services import rag
        from langchain_core.documents import Document
        rag.invalidate_retrieval_cache()
        doc = Document(page_content="Evidence", metadata={"source":"notes.txt","chunk":1,"page":1})
        with patch("app.services.rag.get_store") as store:
            store.return_value.similarity_search_with_score.return_value = [(doc, 0.2)]
            self.assertEqual(rag.retrieve("same question")[0][0]["content"], "Evidence")
            rag.retrieve("same question")
            self.assertEqual(store.return_value.similarity_search_with_score.call_count, 1)
            with patch("app.services.rag.connect"), patch("app.services.rag.utility.has_collection", return_value=True), patch("app.services.rag.Collection"):
                rag.delete_chunks("a" * 32)
            rag.retrieve("same question")
            self.assertEqual(store.return_value.similarity_search_with_score.call_count, 2)
        rag.invalidate_retrieval_cache()

    def test_existing_history_schema_is_upgraded_without_losing_rows(self):
        with storage.connection() as db:
            db.execute("DROP TABLE messages")
            db.execute("""CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT NOT NULL,
                question TEXT NOT NULL, answer TEXT NOT NULL, sources TEXT NOT NULL,
                status TEXT NOT NULL, duration_ms INTEGER NOT NULL, retrieval_ms INTEGER NOT NULL,
                created_at TEXT NOT NULL)""")
            db.execute("INSERT INTO messages VALUES (1,'old-session','old question','old answer','[]','no_context',100,0,?)",(storage.now(),))
        storage.initialize()
        old = storage.history("old-session")
        self.assertEqual(old[0]["answer"], "old answer")
        self.assertIsNone(old[0]["first_token_ms"])


if __name__ == "__main__":
    unittest.main()
