import os
import logging
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
django.setup()

from django.apps import apps
from simo.mcp_server.app import mcp
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
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


def create_app():
    load_tools_from_apps()
    app = create_streamable_http_app(
        server=mcp,
        streamable_http_path="/",
        auth=mcp.auth,
        json_response=True,
        stateless_http=True,
        debug=True,
        middleware=[Middleware(LogExceptions)],
    )
    return app
