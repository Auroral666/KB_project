"""Retrieve evidence, generate replies and persist only complete answers."""
import logging
import time

from app.repositories import workspace
from app.services import rag
from app.services.knowledge_graph import from_sources
from app.config import config

logger = logging.getLogger("kb_project")


def _retrieve(question):
    if workspace.documents():
        return rag.retrieve(question)
    return [], 0


def _save(question, answer, sources, session_id, started, retrieval_ms, first_token_ms=None):
    duration_ms = round((time.perf_counter() - started) * 1000)
    status = "answered" if sources else "no_context"
    session_id, message_id = workspace.save_message(
        session_id, question, answer, sources, status, duration_ms, retrieval_ms, first_token_ms)
    result = {"answer": answer, "sources": sources, "status": status, "session_id": session_id,
              "message_id": message_id, "duration_ms": duration_ms, "retrieval_ms": retrieval_ms}
    if first_token_ms is not None:
        result["first_token_ms"] = first_token_ms
    return result


def ask(question, session_id=None):
    started = time.perf_counter()
    rewritten = rag.rewrite_question(question, workspace.recent_history(session_id, config.history_turns))
    sources, retrieval_ms = _retrieve(rewritten)
    answer = rag.answer(rewritten, sources)
    return {**_save(question, answer, sources, session_id, started, retrieval_ms),
            "rewritten_question": rewritten, "graph": from_sources(sources)}


def stream(question, session_id=None):
    """Yield transport-independent events; an interrupted reply is never saved."""
    started = time.perf_counter()
    first_token_ms = None
    fragments = []
    try:
        yield {"type": "status", "message": "正在检索知识库…"}
        rewritten = rag.rewrite_question(question, workspace.recent_history(session_id, config.history_turns))
        sources, retrieval_ms = _retrieve(rewritten)
        yield {"type": "sources", "sources": sources, "retrieval_ms": retrieval_ms}
        graph = from_sources(sources)
        yield {"type": "graph", "graph": graph, "rewritten_question": rewritten}
        for text in rag.stream_answer(rewritten, sources):
            if not text:
                continue
            if first_token_ms is None:
                first_token_ms = round((time.perf_counter() - started) * 1000)
            fragments.append(text)
            yield {"type": "delta", "text": text}
        answer = "".join(fragments)
        if not answer:
            raise ValueError("Model returned no answer")
        yield {"type": "done", "graph": graph, "rewritten_question": rewritten, **_save(question, answer, sources, session_id, started,
                                     retrieval_ms, first_token_ms)}
    except Exception:
        logger.exception("Streaming question answering failed")
        yield {"type": "error", "message": "回答未能完成，请检查模型或向量服务后重试。"}
