"""Request-local inference records. Never retain prompts, images or credentials."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from urllib.parse import urlsplit
from hashlib import sha256
from pathlib import Path
import json

_calls: ContextVar[list | None] = ContextVar("model_calls", default=None)
_purpose: ContextVar[str] = ContextVar("model_purpose", default="visual_analysis")


@contextmanager
def capture_model_calls(purpose: str = "visual_analysis"):
    calls = []
    calls_token = _calls.set(calls)
    purpose_token = _purpose.set(purpose)
    try:
        yield calls
    finally:
        _purpose.reset(purpose_token)
        _calls.reset(calls_token)


@contextmanager
def model_purpose(purpose: str):
    token = _purpose.set(purpose)
    try:
        yield
    finally:
        _purpose.reset(token)


def record_model_call(provider, started, elapsed_ms, *, response_model=None, error=None):
    calls = _calls.get()
    if calls is not None:
        try:
            host = urlsplit(provider.get("base_url", "")).hostname
        except ValueError:
            host = None
        calls.append({
            "purpose": _purpose.get(),
            "provider": provider.get("name"),
            "endpoint_host": host,
            "requested_model": provider.get("model"),
            "response_model": response_model[:256] if isinstance(response_model, str) else None,
            "started_at": started,
            "duration_ms": elapsed_ms,
            "status": "failed" if error else "success",
            "error_type": type(error).__name__ if error else None,
        })


def trace_time():
    return datetime.now(timezone.utc).isoformat()


def report_provenance(module_path, calls):
    path = Path(module_path)
    return {"implementation": path.name, "implementation_sha256": sha256(path.read_bytes()).hexdigest(),
            "model_calls": list(calls)}


def read_phone_model_calls(output_dir):
    path = Path(output_dir) / "model_calls.jsonl"
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        return [{"purpose": "phone_navigation", "status": "trace_error", "error_type": type(exc).__name__}]
    calls = []
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("invalid trace record")
            calls.append(value)
        except ValueError as exc:
            calls.append({"purpose": "phone_navigation", "status": "trace_error", "error_type": type(exc).__name__})
    return calls
