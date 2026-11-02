"""Small fail-open Langfuse adapter with generator-safe, explicit trace parenting."""
import contextvars
import inspect
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from functools import lru_cache, wraps
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values

FOLDER = Path(__file__).resolve().parents[1]
PROJECT = FOLDER.parent
logger = logging.getLogger("kb_project.langfuse")
current = contextvars.ContextVar("kb_observation", default=None)
_client = None
_initialized = False
_lock = threading.Lock()
_last_failure = None
last_trace_id = None


@lru_cache(maxsize=2)
def file_settings(path):
    return dotenv_values(path)


def setting(name, default=""):
    return os.getenv(name, file_settings(FOLDER / ".env").get(name) or default)


def enabled():
    return str(setting("LANGFUSE_ENABLED", "true")).lower() == "true"


def _failure(exc):
    global _last_failure
    category = type(exc).__name__
    if category != _last_failure:
        logger.warning("Langfuse observation unavailable (%s); application continues.", category)
        _last_failure = category


def sanitize(value=None, *, data=None):
    """Capture business data, never client objects, credentials or giant vectors."""
    if data is not None:
        value = data
    secrets = [v for k, v in {**file_settings(PROJECT / ".env"), **file_settings(FOLDER / ".env"),
                              **os.environ}.items()
               if v and any(word in k.lower() for word in ("api_key", "secret_key", "public_key"))]

    def project(item, depth=0):
        if depth > 7:
            return {"type": type(item).__name__}
        if isinstance(item, str):
            for secret in secrets:
                item = item.replace(secret, "[REDACTED]")
            return item
        if item is None or isinstance(item, (bool, int, float)):
            return item
        if isinstance(item, Path):
            return item.name
        if isinstance(item, bytes):
            return {"bytes": len(item)}
        if isinstance(item, dict):
            return {str(k): "[REDACTED]" if any(word in str(k).lower() for word in
                    ("api_key", "secret_key", "public_key", "authorization", "password"))
                    else project(v, depth + 1) for k, v in item.items()}
        if isinstance(item, (list, tuple)):
            if len(item) > 16 and all(isinstance(v, (float, int)) for v in item):
                return {"dimensions": len(item), "preview": list(item[:8])}
            projected = [project(v, depth + 1) for v in item[:50]]
            return projected if len(item) <= 50 else {"count": len(item), "preview": projected, "truncated": True}
        if hasattr(item, "page_content"):
            return project({"content": item.page_content, "metadata": item.metadata}, depth + 1)
        return {"type": type(item).__name__}

    result = project(value)
    rendered = json.dumps(result, ensure_ascii=False, default=str)
    try:
        limit = max(256, int(setting("LANGFUSE_MAX_CONTENT_CHARS", "20000")))
    except (TypeError, ValueError):
        limit = 20000
    return result if len(rendered) <= limit else {"truncated": True, "preview": rendered[:limit]}


def client():
    global _client, _initialized
    if not enabled():
        return None
    with _lock:
        if not _initialized:
            _initialized = True
            try:
                from langfuse import Langfuse
                if not setting("LANGFUSE_PUBLIC_KEY") or not setting("LANGFUSE_SECRET_KEY"):
                    raise ValueError("Missing Langfuse project credentials")
                _client = Langfuse(public_key=setting("LANGFUSE_PUBLIC_KEY"),
                    secret_key=setting("LANGFUSE_SECRET_KEY"), base_url=setting("LANGFUSE_BASE_URL"),
                    environment=setting("LANGFUSE_ENVIRONMENT", "kb-project"),
                    timeout=5, flush_at=16, flush_interval=1, mask=sanitize)
            except Exception as exc:
                _failure(exc)
        return _client


class Observation:
    def __init__(self, name, inputs, kind="span", model=None):
        global last_trace_id
        self.name, self.kind = name, kind
        self.started = time.perf_counter()
        self.sdk = None
        self.closed = False
        self.fragments = []
        self.result = None
        self.first_token_ms = None
        self.usage = {}
        self.metadata = {}
        self.level = "DEFAULT"
        parent = current.get()
        self.trace_id = parent.trace_id if parent else uuid4().hex
        sdk = client()
        if sdk:
            try:
                options = {"name": name, "as_type": kind}
                if str(setting("LANGFUSE_CAPTURE_CONTENT", "true")).lower() == "true":
                    options["input"] = sanitize(inputs)
                if model:
                    options["model"] = model
                # A remote trace_context would synthesize a missing parent for a root.
                # SDK observation objects create real children without active OTel context.
                owner = parent.sdk if parent and parent.sdk else sdk
                self.sdk = owner.start_observation(**options)
                self.trace_id = self.sdk.trace_id
                if parent is None:
                    last_trace_id = self.trace_id
            except Exception as exc:
                _failure(exc)

    def update(self, **fields):
        if self.sdk and not self.closed:
            try:
                self.sdk.update(**fields)
            except Exception as exc:
                _failure(exc)

    def feed(self, item):
        text = item if isinstance(item, str) else getattr(item, "content", "")
        if isinstance(item, dict):
            if item.get("type") == "delta":
                text = item.get("text", "")
            elif item.get("type") in {"done", "error"}:
                self.result = item
                if item["type"] == "error":
                    self.level = "ERROR"
                for key in ("session_id", "message_id", "first_token_ms", "retrieval_ms", "duration_ms", "status"):
                    if key in item:
                        self.metadata[key] = item[key]
        if isinstance(text, str) and text:
            self.fragments.append(text)
            if self.first_token_ms is None:
                self.first_token_ms = round((time.perf_counter() - self.started) * 1000)
                if self.kind == "generation":
                    self.update(completion_start_time=datetime.now(timezone.utc))
        usage = getattr(item, "usage_metadata", None) or {}
        fallback = (getattr(item, "response_metadata", None) or {}).get("token_usage", {}) or {}
        for target, primary, secondary in (("input", "input_tokens", "prompt_tokens"),
                                            ("output", "output_tokens", "completion_tokens"),
                                            ("total", "total_tokens", "total_tokens")):
            count = usage.get(primary, fallback.get(secondary))
            if isinstance(count, int):
                self.usage[target] = count

    def finish(self, result=None, error=None, cancelled=False):
        if self.closed:
            return
        self.metadata["observed_duration_ms"] = round((time.perf_counter() - self.started) * 1000)
        if self.first_token_ms is not None:
            self.metadata["observed_first_token_ms"] = self.first_token_ms
        if error:
            self.level = "ERROR"
            self.metadata["error_type"] = type(error).__name__
        if cancelled:
            self.level = "WARNING"
            self.metadata["cancelled"] = True
        output = result if result is not None else self.result
        if output is None and self.fragments:
            output = "".join(self.fragments)
        if isinstance(output, dict) and output.get("session_id") and self.sdk:
            try:
                from langfuse import propagate_attributes
                # The session ID becomes available after the original app saves its reply.
                # Propagate publicly through a short context; no token survives an SSE yield.
                from opentelemetry.trace import use_span
                with use_span(self.sdk._otel_span, end_on_exit=False):
                    with propagate_attributes(session_id=output["session_id"]):
                        pass
            except Exception as exc:
                _failure(exc)
        fields = {"metadata": sanitize(self.metadata), "level": self.level}
        if str(setting("LANGFUSE_CAPTURE_CONTENT", "true")).lower() == "true":
            fields["output"] = sanitize(output)
        if self.usage and self.kind in {"generation", "embedding"}:
            fields["usage_details"] = self.usage
        self.update(**fields)
        if self.sdk:
            try:
                self.sdk.end()
            except Exception as exc:
                _failure(exc)
        self.closed = True


def observe(function, name, *, kind="span", nested_only=False, model=None, generation=False):
    signature = inspect.signature(function)

    def begin(args, kwargs):
        values = dict(signature.bind_partial(*args, **kwargs).arguments)
        values.pop("self", None)
        return Observation(name, values, kind=kind, model=model)

    if inspect.isgeneratorfunction(function) or generation:
        @wraps(function)
        def generator(*args, **kwargs):
            if not enabled() or (nested_only and current.get() is None):
                yield from function(*args, **kwargs)
                return
            observation = begin(args, kwargs)
            iterator = None
            try:
                if generation:
                    kwargs.setdefault("stream_usage", True)
                iterator = iter(function(*args, **kwargs))
                while True:
                    token = current.set(observation)
                    try:
                        item = next(iterator)
                    except StopIteration:
                        break
                    finally:
                        current.reset(token)
                    observation.feed(item)
                    # Do not leave contextvars/OTel tokens attached across an SSE yield.
                    if isinstance(item, dict) and item.get("type") in {"done", "error"}:
                        observation.finish()
                    yield item
                observation.finish()
            except GeneratorExit:
                observation.finish(cancelled=True)
                raise
            except BaseException as exc:
                observation.finish(error=exc)
                raise
            finally:
                if iterator is not None and hasattr(iterator, "close"):
                    iterator.close()
        return generator

    @wraps(function)
    def normal(*args, **kwargs):
        if not enabled() or (nested_only and current.get() is None):
            return function(*args, **kwargs)
        observation = begin(args, kwargs)
        token = current.set(observation)
        try:
            result = function(*args, **kwargs)
            observation.finish(result)
            return result
        except BaseException as exc:
            observation.finish(error=exc)
            raise
        finally:
            current.reset(token)
    return normal


def shutdown():
    if _client:
        try:
            _client.flush()
            _client.shutdown()
        except Exception as exc:
            _failure(exc)
