"""Single indexing worker with durable status and restart recovery."""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from app.config import config
from app.repositories import workspace
from app.services import documents

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="index-job")
submission_lock = threading.RLock()
logger = logging.getLogger("kb_project")


def submit(filename, stream):
    with submission_lock:
        if len(workspace.active_jobs()) >= 20:
            raise ValueError("待处理任务已达20个，请稍后上传。")
        doc_id, name, suffix, size, path = documents.stage(filename, stream)
        job_id = uuid4().hex
        try:
            workspace.add_job(job_id, doc_id, name, suffix, size)
            _executor.submit(process, job_id)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return workspace.job(job_id)


def process(job_id):
    job = workspace.job(job_id)
    if not job or job["status"] not in {"queued", "running"}:
        return
    path = config.upload_dir / (job["doc_id"] + job["extension"])
    try:
        workspace.update_job(job_id, "running", "semantic_chunking")
        documents.index_staged(job["doc_id"], job["name"], job["extension"], job["size"], path,
            progress=lambda stage: workspace.update_job(job_id, "running", stage), replace=job["status"] == "running")
        workspace.update_job(job_id, "succeeded", "complete")
    except Exception as exc:
        logger.exception("Index job %s failed", job_id)
        # Keep a useful reason without exposing SDK request headers or credentials.
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__ + "：处理失败，请检查服务连接和日志。"
        workspace.update_job(job_id, "failed", "failed", reason[:500])


def recover():
    for job in workspace.active_jobs():
        # A crash may have occurred between inventory commit and final status update.
        if workspace.document(job["doc_id"]):
            workspace.update_job(job["id"], "succeeded", "complete")
        else:
            _executor.submit(process, job["id"])
