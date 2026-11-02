"""Workspace pages, service health and read-only conversation views."""
from fastapi import APIRouter, Query, Request
from fastapi.templating import Jinja2Templates

from app.config import WEB_DIR, config
from app.repositories import workspace
from app.services import rag, knowledge_graph
import logging

router = APIRouter()
templates = Jinja2Templates(directory=WEB_DIR / "templates")


@router.get("/")
@router.get("/chat")
@router.get("/knowledge")
@router.get("/insights")
def page(request: Request):
    return templates.TemplateResponse(request=request, name="workspace.html", context={"page": request.url.path})


@router.get("/health")
def health():
    return {"status": "ok", "application": "knowledge-studio"}


@router.get("/api/status")
def get_status():
    return rag.status()


@router.get("/api/overview")
def get_overview(days: int = Query(7, ge=1, le=30)):
    return workspace.overview(days)


@router.get("/api/sessions")
def get_sessions():
    return {"sessions": workspace.sessions()}


@router.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    messages = workspace.history(session_id)
    if config.neo4j_enabled:
        try:
            sources = knowledge_graph.attach_relations([s for m in messages for s in m["sources"]])
            offset = 0
            for message in messages:
                count = len(message["sources"])
                message["sources"] = sources[offset:offset + count]
                offset += count
        except Exception:
            logging.getLogger("kb_project").warning("Could not restore historical graph context", exc_info=True)
    return {"messages": messages}
