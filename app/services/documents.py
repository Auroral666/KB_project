"""Own uploaded files, document indexing, cleanup and original-text access."""
import logging
from pathlib import Path
from uuid import uuid4

from app.config import config
from app.repositories import workspace
from app.services import rag, knowledge_graph
from app.services.document_parser import SUPPORTED_EXTENSIONS, load_chunks, load_documents

logger = logging.getLogger("kb_project")


class UploadTooLargeError(ValueError):
    """The upload exceeded the workspace's configured file size limit."""


def require_document(doc_id):
    doc = workspace.document(doc_id)
    if not doc:
        raise FileNotFoundError("文档不存在，可能已被移除。")
    return doc


def original(doc_id):
    """Return the original file, or its complete text, never retrieved excerpts."""
    doc = require_document(doc_id)
    path = config.upload_dir / (doc["id"] + doc["extension"])
    if not path.is_file():
        raise FileNotFoundError("原始文档已移除，无法定位原文。")
    if doc["extension"] == ".pdf":
        return path
    return {"name": doc["name"], "format": "text", "pages": [
        {"number": i + 1, "text": page.page_content}
        for i, page in enumerate(load_documents(path))]}


def download(doc_id):
    doc = require_document(doc_id)
    path = config.upload_dir / (doc["id"] + doc["extension"])
    if not path.is_file():
        raise FileNotFoundError("文档文件不存在。")
    return doc, path


def stage(filename, source):
    """Copy the upload before the request stream closes."""
    name = (filename or "").replace("\\", "/").split("/")[-1]
    suffix = Path(name).suffix.lower()
    if not name or len(name) > 200 or suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError("请选择 PDF、DOCX、TXT 或 Markdown 文件，文件名不超过 200 字符。")
    doc_id = uuid4().hex
    path = config.upload_dir / (doc_id + suffix)
    size = 0
    try:
        with path.open("wb") as target:
            while block := source.read(1024 * 1024):
                size += len(block)
                if size > config.max_upload_bytes:
                    raise UploadTooLargeError("文件不能超过 20 MB，请拆分后上传。")
                target.write(block)
        if not size:
            raise ValueError("文件为空，请选择包含内容的文档。")
        return doc_id, name, suffix, size, path
    except Exception:
        path.unlink(missing_ok=True)
        raise


def index_staged(doc_id, name, suffix, size, path, progress=lambda stage: None, replace=False):
    indexing_started = False
    try:
        chunks = rag.semantic_chunks(path)
        if not chunks:
            raise ValueError("文档未提取到文字。扫描版 PDF 请先进行文字识别。")
        progress("extracting_relations")
        facts = knowledge_graph.extract(chunks) if config.neo4j_enabled else []
        with rag.operation_lock:
            indexing_started = True
            # Retry/restart replaces this document's partial writes, without touching other documents.
            if replace:
                if config.neo4j_enabled:
                    knowledge_graph.remove(doc_id)
                rag.delete_chunks(doc_id)
            progress("writing_vectors")
            rag.add_chunks(doc_id, name, chunks)
            if config.neo4j_enabled:
                progress("writing_graph")
                knowledge_graph.write(doc_id, name, facts)
            workspace.add_document(doc_id, name, suffix, size, len(chunks))
        return workspace.document(doc_id)
    except Exception:
        cleanup_failed = False
        if indexing_started:
            try:
                with rag.operation_lock:
                    rag.delete_chunks(doc_id)
                    if config.neo4j_enabled:
                        knowledge_graph.remove(doc_id)
            except Exception:
                cleanup_failed = True
                logger.exception("Could not roll back document %s", doc_id)
        if not cleanup_failed:
            path.unlink(missing_ok=True)
        raise


def create(filename, source):
    """Compatibility endpoint; the page uses durable background jobs."""
    return index_staged(*stage(filename, source))


def remove(doc_id):
    doc = require_document(doc_id)
    with rag.operation_lock:
        if config.neo4j_enabled:
            knowledge_graph.remove(doc_id)
        rag.delete_chunks(doc["id"])
        workspace.remove_document(doc_id)
        (config.upload_dir / (doc["id"] + doc["extension"])).unlink(missing_ok=True)


def clear():
    with rag.operation_lock:
        if config.neo4j_enabled:
            knowledge_graph.clear()
        rag.clear()
        for doc in workspace.documents():
            workspace.remove_document(doc["id"])
            (config.upload_dir / (doc["id"] + doc["extension"])).unlink(missing_ok=True)
