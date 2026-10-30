"""Serve the built web/ (``npm run build`` → web/dist) from the API — one origin in Docker.

``/assets/*`` is content-hashed by Vite → cached immutable. Any other GET outside ``/api``
falls back to a top-level dist file (favicon) or ``index.html`` (SPA routes), both no-cache
so a rebuild is picked up. Unmatched ``/api/*`` and missing assets stay JSON 404s.

The fallback is a 404 handler rather than a catch-all route, so routers included after it
are never shadowed. No-op when the dist dir is missing (dev: Vite serves the frontend).
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

from utils.logging import get_logger

log = get_logger(__name__)

IMMUTABLE = "public, max-age=31536000, immutable"
NO_CACHE = "no-cache"


class _HashedAssets(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code in (200, 304):
            response.headers["Cache-Control"] = IMMUTABLE
        return response


def _spa_path(path: str) -> bool:
    return not (path == "/api" or path.startswith(("/api/", "/assets/")))


def mount_web(app: FastAPI, dist: Path) -> bool:
    """Serve ``dist`` at ``/`` if it holds a build; returns whether it was mounted."""
    dist = dist.resolve()
    index = dist / "index.html"
    if not index.is_file():
        log.info("api.web.not_mounted", dist=str(dist))
        return False
    if (dist / "assets").is_dir():
        app.mount("/assets", _HashedAssets(directory=dist / "assets"), name="assets")

    @app.exception_handler(StarletteHTTPException)
    async def _spa_fallback(request: Request, exc: StarletteHTTPException) -> Response:
        path = request.url.path
        if exc.status_code != 404 or request.method not in ("GET", "HEAD") or not _spa_path(path):
            return await http_exception_handler(request, exc)
        candidate = (dist / path.lstrip("/")).resolve()
        if candidate != dist and candidate.is_relative_to(dist) and candidate.is_file():
            return FileResponse(candidate, headers={"Cache-Control": NO_CACHE})
        return FileResponse(index, headers={"Cache-Control": NO_CACHE})

    log.info("api.web.mounted", dist=str(dist))
    return True
