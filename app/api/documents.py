"""HTTP responses for document upload, removal, download and original viewing."""
import logging
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.repositories import workspace
from app.services import documents, index_jobs

router = APIRouter()
logger = logging.getLogger("kb_project")


@router.post("/api/index-jobs", status_code=202)
def enqueue(file: UploadFile = File(...)):
    try:
        job = index_jobs.submit(file.filename, file.file)
        return {"task_id": job["id"], "job": job}
    except documents.UploadTooLargeError as exc:
        raise HTTPException(413, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("Could not submit indexing job")
        raise HTTPException(503, "暂时无法创建建库任务，请检查存储和服务日志。") from exc
    finally:
        file.file.close()


@router.get("/api/index-jobs")
def list_jobs():
    return {"jobs": workspace.jobs()}


@router.get("/api/index-jobs/{job_id}")
def get_job(job_id: str):
    job = workspace.job(job_id)
    if not job:
        raise HTTPException(404, "建库任务不存在。")
    return {"job": job}


@router.get("/api/documents")
def list_documents():
    return {"documents": workspace.documents()}


@router.get("/api/documents/{doc_id}/download")
def download(doc_id: str):
    try:
        doc, path = documents.download(doc_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return FileResponse(path, filename=doc["name"], media_type="application/octet-stream")


@router.get("/api/documents/{doc_id}/original")
def original(doc_id: str):
    try:
        result = documents.original(doc_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        logger.exception("Original document could not be read")
        raise HTTPException(422, "无法读取完整原文，请下载文件查看。") from exc
    if isinstance(result, Path):
        return FileResponse(result, media_type="application/pdf", headers={"Cache-Control": "private, max-age=300"})
    return result


@router.post("/rag/create/")
def upload(file: UploadFile = File(...)):
    try:
        doc = documents.create(file.filename, file.file)
        return {"status": "success", "message": f"已收录 {doc['name']}，生成 {doc['chunks']} 个知识片段。",
                "document": doc}
    except documents.UploadTooLargeError as exc:
        raise HTTPException(413, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("Document indexing failed")
        raise HTTPException(503, "文档处理失败，请检查文档格式及本地向量服务后重试。") from exc
    finally:
        file.file.close()


@router.delete("/api/documents/{doc_id}")
def remove(doc_id: str):
    try:
        documents.remove(doc_id)
        return {"message": "文档及对应知识片段已移除。"}
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        logger.exception("Document deletion failed")
        raise HTTPException(503, "移除失败，请检查向量服务后重试。") from exc


@router.post("/rag/clear/")
def clear():
    try:
        with index_jobs.submission_lock:
            if workspace.active_jobs():
                raise HTTPException(409, "仍有建库任务处理中，请完成后再清空。")
            documents.clear()
        return {"message": "当前工作台知识库已清空，对话记录已保留。"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Knowledge reset failed")
        raise HTTPException(503, "清空失败，请检查向量服务后重试。") from exc
