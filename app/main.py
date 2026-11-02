"""Compose the application: lifecycle, middleware, routes and static assets."""
import mimetypes
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api import chat, documents, workspace
from app.config import WEB_DIR, config
from app.repositories import workspace as repository
from app.services import rag

# Windows may register ES modules as text/plain; PDF.js requires executable JavaScript.
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("application/wasm", ".wasm")


@asynccontextmanager
async def lifespan(app):
    repository.initialize()
    if config.warmup_on_start and repository.documents():
        threading.Thread(target=rag.warmup, name="retrieval-warmup", daemon=True).start()
    yield


app = FastAPI(title="知屿 Knowledge Studio", version="1.0.0", lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")


@app.middleware("http")
async def local_requests(request, call_next):
    origin = request.headers.get("origin")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin != str(request.base_url).rstrip("/"):
        return JSONResponse({"detail": "请从当前工作台页面执行操作。"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


app.include_router(workspace.router)
app.include_router(documents.router)
app.include_router(chat.router)
