"""Workspace pages, service health and read-only conversation views."""
from fastapi import APIRouter, Query, Request
from fastapi.templating import Jinja2Templates

from app.config import WEB_DIR
from app.repositories import workspace
from app.services import rag

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
    return {"messages": workspace.history(session_id)}
