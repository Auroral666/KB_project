"""Project-local configuration. Credentials never leave the server."""
import os
from pathlib import Path

from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
WEB_DIR = APP_DIR / "web"
RUNTIME_DIR = PROJECT_ROOT / "temp" / "runtime"
load_dotenv(PROJECT_ROOT / ".env", override=True, encoding="utf-8-sig")


class RagConfig:
    fastapi_host = os.getenv("fastapi_host", "127.0.0.1")
    fastapi_port = int(os.getenv("fastapi_port", "8010"))
    milvus_host = os.getenv("milvus_host", "localhost")
    milvus_port = os.getenv("milvus_port", "19530")
    milvus_collection_name = os.getenv("milvus_collection_name", "kb_project_knowledge")
    base_url = os.getenv("openai_base_url")
    api_key = os.getenv("openai_api_key")
    llm_model_name = os.getenv("openai_llm_model_name", "deepseek-v4-flash")
    text_embeddings_model_path = os.getenv("text_embeddings_model_path", "jinaai/jina-embeddings-v3")
    upload_dir = PROJECT_ROOT / "upload_files"
    database = PROJECT_ROOT / "data" / "workspace.db"
    max_upload_bytes = 20 * 1024 * 1024
    embedding_cpu_threads = max(1, int(os.getenv("embedding_cpu_threads", "2")))
    warmup_on_start = os.getenv("warmup_on_start", "true").lower() == "true"
    llm_thinking_enabled = os.getenv("llm_thinking_enabled", "false").lower() == "true"


config = RagConfig()
