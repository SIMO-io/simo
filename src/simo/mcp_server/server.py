import os
import json
import time
import uuid
import logging
from typing import Any

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
django.setup()

from django.apps import apps
from simo.mcp_server.app import mcp
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import StreamingResponse
from fastmcp.server.http import create_streamable_http_app


log = logging.getLogger("simo")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname).1s %(name)s: %(message)s",
)


def load_tools_from_apps() -> None:
    import importlib.util

    for cfg in apps.get_app_configs():
        mod_name = f"{cfg.name}.mcp"

        # Only attempt import if module exists
        if importlib.util.find_spec(mod_name) is None:
            continue

        try:
            importlib.import_module(mod_name)
            log.info("Loaded MCP tools: %s", mod_name)
        except Exception:
            # Keep the server up; log full traceback and continue
            log.exception("Failed to import %s", mod_name)


class LogExceptions(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        try:
            return await call_next(request)
        except Exception:
            log.exception("Unhandled exception in %s %s", request.method, request.url.path)
            raise  # Let Starlette/Uvicorn still return 500


def _mcp_log_max_bytes() -> int:
    try:
        return max(0, int(os.environ.get("SIMO_MCP_LOG_MAX_BYTES", "16384")))
    except Exception:
        return 16384


_SENSITIVE_KEYS = {
    "authorization",
    "hub-secret",
    "secret",
    "secret_key",
    "password",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "private_key",
    "mcp-token",
}


def _truncate_str(val: str, *, limit: int = 400) -> str:
    if len(val) <= limit:
        return val
    return val[:limit] + f"…(truncated,{len(val) - limit} chars)"


def _redact_payload(obj: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return "…(max depth)"
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            key = str(k)
            if key.lower() in _SENSITIVE_KEYS:
                out[key] = "***"
            else:
                out[key] = _redact_payload(v, depth=depth + 1)
        return out
    if isinstance(obj, (list, tuple)):
        return [_redact_payload(v, depth=depth + 1) for v in obj]
    if isinstance(obj, str):
        return _truncate_str(obj)
    return obj


def _summarize_mcp_json(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    # Try to extract MCP-ish tool name from common formats.
    tool_name = None
    if isinstance(payload.get("params"), dict):
        tool_name = payload["params"].get("name")
    tool_name = tool_name or payload.get("name")

    method = payload.get("method")
    req_type = payload.get("type")
    rid = payload.get("id")

    out: dict[str, Any] = {}
    if req_type is not None:
        out["type"] = req_type
    if method is not None:
        out["method"] = method
    if rid is not None:
        out["id"] = rid
    if tool_name is not None:
        out["tool"] = tool_name
    return out or None


class LogMcpHttp(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        req_id = uuid.uuid4().hex[:10]
        started = time.time()
        max_bytes = _mcp_log_max_bytes()

        body_bytes = b""
        body_json = None
        body_note = None
        try:
            body_bytes = await request.body()
            if body_bytes:
                try:
                    body_json = json.loads(body_bytes)
                except Exception:
                    body_note = f"non-json body bytes={len(body_bytes)}"
        except Exception as e:
            body_note = f"failed reading body: {e}"

        client = getattr(request, "client", None)
        client_host = getattr(client, "host", None) or "?"

        summary = _summarize_mcp_json(body_json) if body_json is not None else None
        if summary is not None:
            log.info("[mcp:%s] req %s %s from=%s summary=%s", req_id, request.method, request.url.path, client_host, summary)
        else:
            log.info("[mcp:%s] req %s %s from=%s", req_id, request.method, request.url.path, client_host)

        if body_json is not None:
            try:
                redacted = _redact_payload(body_json)
                encoded = json.dumps(redacted, ensure_ascii=False, default=str).encode("utf-8")
                if max_bytes and len(encoded) > max_bytes:
                    log.info("[mcp:%s] req_body %s", req_id, encoded[:max_bytes].decode("utf-8", errors="replace") + f"…(truncated,{len(encoded) - max_bytes} bytes)")
                else:
                    log.info("[mcp:%s] req_body %s", req_id, encoded.decode("utf-8", errors="replace"))
            except Exception:
                log.exception("[mcp:%s] failed to log request body", req_id)
        elif body_note:
            log.info("[mcp:%s] req_body %s", req_id, body_note)

        response = await call_next(request)

        # If the response is streaming, tee the iterator so we can log the
        # payload without breaking streaming semantics.
        if isinstance(response, StreamingResponse):
            orig_iter = response.body_iterator
            buf = bytearray()

            async def _tee():
                nonlocal buf
                try:
                    async for chunk in orig_iter:
                        if chunk and max_bytes and len(buf) < max_bytes:
                            remaining = max_bytes - len(buf)
                            buf.extend(chunk[:remaining])
                        yield chunk
                finally:
                    took_ms = int((time.time() - started) * 1000)
                    if buf:
                        txt = buf.decode("utf-8", errors="replace")
                        log.info("[mcp:%s] resp status=%s ms=%s body=%s", req_id, getattr(response, "status_code", "?"), took_ms, _truncate_str(txt, limit=2000))
                    else:
                        log.info("[mcp:%s] resp status=%s ms=%s (stream, empty preview)", req_id, getattr(response, "status_code", "?"), took_ms)

            response.body_iterator = _tee()
            return response

        took_ms = int((time.time() - started) * 1000)
        resp_body = getattr(response, "body", b"")
        if not resp_body:
            log.info("[mcp:%s] resp status=%s ms=%s", req_id, getattr(response, "status_code", "?"), took_ms)
            return response

        try:
            if isinstance(resp_body, (bytes, bytearray)):
                txt = bytes(resp_body).decode("utf-8", errors="replace")
            else:
                txt = str(resp_body)
            # Try to redact response JSON too.
            try:
                parsed = json.loads(txt)
                txt = json.dumps(_redact_payload(parsed), ensure_ascii=False, default=str)
            except Exception:
                pass
            log.info("[mcp:%s] resp status=%s ms=%s body=%s", req_id, getattr(response, "status_code", "?"), took_ms, _truncate_str(txt, limit=2000))
        except Exception:
            log.exception("[mcp:%s] failed to log response body", req_id)
            log.info("[mcp:%s] resp status=%s ms=%s", req_id, getattr(response, "status_code", "?"), took_ms)

        return response


def create_app():
    load_tools_from_apps()
    app = create_streamable_http_app(
        server=mcp,
        streamable_http_path="/",
        auth=mcp.auth,
        json_response=True,
        stateless_http=True,
        debug=True,
        middleware=[Middleware(LogMcpHttp), Middleware(LogExceptions)],
    )
    return app
