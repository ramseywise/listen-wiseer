"""
FastAPI backend for the web player (web/): Navidrome proxy now; agent chat, playlists and
play tracking in later rounds. Owns the Navidrome credentials — they never reach the browser.

Run:
    make api    # uvicorn --factory api.app:create_app on 127.0.0.1:8000
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api import archive, chat, library, playable, player, playlists, radio
from api.deps import DbConnect
from api.static import mount_web
from etl.db import get_connection
from paths import WEB_DIST_DIR
from sources.subsonic import SubsonicClient, SubsonicError, SubsonicNotFound, SubsonicUnavailable
from utils.config import settings
from utils.logging import configure_logging, get_logger

log = get_logger(__name__)


def _add_error_handlers(app: FastAPI) -> None:
    """Subsonic failures → ``{"detail": str}``: 404 missing item, 503 Navidrome down, 502 other."""

    @app.exception_handler(SubsonicNotFound)
    async def _not_found(_request: Request, exc: SubsonicNotFound) -> JSONResponse:
        return JSONResponse({"detail": exc.message}, status_code=404)

    @app.exception_handler(SubsonicUnavailable)
    async def _unavailable(request: Request, exc: SubsonicUnavailable) -> JSONResponse:
        log.warning("api.navidrome_unavailable", path=request.url.path, error=str(exc))
        return JSONResponse({"detail": "Navidrome is unavailable"}, status_code=503)

    @app.exception_handler(SubsonicError)
    async def _upstream(request: Request, exc: SubsonicError) -> JSONResponse:
        log.warning("api.navidrome_error", path=request.url.path, code=exc.code, error=exc.message)
        return JSONResponse({"detail": f"Navidrome error: {exc.message}"}, status_code=502)


def create_app(
    *,
    subsonic: SubsonicClient | None = None,
    db_connect: DbConnect | None = None,
    web_dist: Path | None = None,
) -> FastAPI:
    """App factory. ``subsonic`` is injected by tests; otherwise built from settings and
    closed on shutdown. ``db_connect`` (tests: a tmp DuckDB file) defaults to the project DB.
    ``web_dist`` (built web/) defaults to WEB_DIST_DIR setting → web/dist; skipped if absent."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if subsonic is None:
            configure_logging(settings.log_level)
        client = subsonic or SubsonicClient.from_settings(settings)
        app.state.subsonic = client
        if subsonic is None:  # production: one graph per process (tests override get_runtime)
            app.state.chat_runtime = await chat.build_runtime()
        log.info("api.started", navidrome=client.base_url)
        try:
            yield
        finally:
            if subsonic is None:
                await client.aclose()
                await chat.close_runtime()

    app = FastAPI(title="listen-wiseer", lifespan=lifespan)
    _add_error_handlers(app)
    app.include_router(library.router, prefix="/api")
    app.state.db_connect = db_connect or get_connection
    app.include_router(playlists.router, prefix="/api")
    app.include_router(player.router, prefix="/api")
    app.include_router(archive.router, prefix="/api")
    app.include_router(playable.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    app.include_router(radio.router, prefix="/api")

    mount_web(app, web_dist or Path(settings.web_dist_dir or WEB_DIST_DIR))
    return app
