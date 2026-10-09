"""Observe AutoGLM's actual streaming calls without modifying its SDK."""
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

TRACE_FILENAME = "model_calls.jsonl"


def trace_phone_client(model_client, output_dir):
    original = model_client.client.chat.completions.create
    path = Path(output_dir) / TRACE_FILENAME

    def create(**kwargs):
        started, clock = datetime.now(timezone.utc).isoformat(), time.monotonic()
        record = {
            "purpose": "phone_navigation", "provider": "openai_compatible",
            "endpoint_host": urlsplit(str(model_client.client.base_url)).hostname,
            "requested_model": kwargs.get("model"), "response_model": None,
            "started_at": started,
        }

        def save(error=None):
            record.update(status="failed" if error else "success", error_type=type(error).__name__ if error else None,
                          duration_ms=round((time.monotonic() - clock) * 1000))
            try:
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            except OSError as exc:
                print(f"⚠️ model trace write failed ({type(exc).__name__})", flush=True)

        try:
            stream = original(**kwargs)
        except Exception as exc:
            save(exc)
            raise

        def chunks():
            error = None
            try:
                for chunk in stream:
                    record["response_model"] = getattr(chunk, "model", None) or record["response_model"]
                    yield chunk
            except BaseException as exc:
                error = exc
                raise
            finally:
                try:
                    stream.close()
                except Exception as exc:
                    record["cleanup_error_type"] = type(exc).__name__
                save(error)
        return chunks()

    model_client.client.chat.completions.create = create


def read_model_calls(output_dir):
    path = Path(output_dir) / TRACE_FILENAME
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
