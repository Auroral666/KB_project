"""Validate questions and adapt synchronous replies or SSE events to HTTP."""
import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services import chat

router = APIRouter()
logger = logging.getLogger("kb_project")


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


def require_question(body):
    question = body.question.strip()
    if not question:
        raise HTTPException(400, "请输入问题。")
    return question


@router.post("/rag/chat/")
def answer(body: ChatRequest):
    question = require_question(body)
    try:
        return chat.ask(question, body.session_id)
    except Exception as exc:
        logger.exception("Question answering failed")
        raise HTTPException(503, "问答服务暂时不可用，请检查模型配置或向量服务后重试。") from exc


@router.post("/rag/chat/stream/")
def stream(body: ChatRequest):
    question = require_question(body)

    def events():
        for event in chat.stream(question, body.session_id):
            yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
