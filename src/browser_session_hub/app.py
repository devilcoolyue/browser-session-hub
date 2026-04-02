"""FastAPI application for Browser Session Hub."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from html import escape
import logging
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import __version__
from .config import BrowserSessionHubConfig
from .models import (
    CreateSessionRequest,
    CreateSessionResponse,
    ErrorResponse,
    HealthResponse,
    SessionListResponse,
    SessionSummary,
)
from .session_manager import BrowserSessionManager, SessionManagerError

logger = logging.getLogger(__name__)


def _build_raw_preview_url(
    config: BrowserSessionHubConfig,
    session: SessionSummary,
) -> str:
    query = urlencode(
        {
            "autoconnect": 1,
            "resize": "scale",
            "reconnect": 1,
            "quality": config.vnc_quality,
            "compression": config.vnc_compress,
        }
    )
    return (
        f"{config.public_scheme}://{config.public_host}:{session.novnc_port}"
        f"/vnc.html?{query}"
    )


def create_app(config: BrowserSessionHubConfig | None = None) -> FastAPI:
    """Create the application."""
    cfg = config or BrowserSessionHubConfig.from_env()
    manager = BrowserSessionManager(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.cleanup_task = None
        if cfg.idle_timeout_seconds <= 0:
            yield
            await run_in_threadpool(manager.shutdown)
            return

        async def _cleanup_loop() -> None:
            while True:
                try:
                    stopped = await run_in_threadpool(manager.cleanup_idle_sessions)
                    if stopped:
                        logger.info("Stopped idle sessions: %s", ", ".join(stopped))
                except Exception:
                    logger.exception("Idle cleanup loop failed")
                await asyncio.sleep(15)

        app.state.cleanup_task = asyncio.create_task(_cleanup_loop())
        try:
            yield
        finally:
            cleanup_task = app.state.cleanup_task
            if cleanup_task is not None:
                cleanup_task.cancel()
            await run_in_threadpool(manager.shutdown)

    app = FastAPI(
        title="Browser Session Hub",
        description="Self-hosted isolated browser sessions with CDP and noVNC previews",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.manager = manager
    app.state.cleanup_task = None

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _http_error(exc: SessionManagerError) -> HTTPException:
        return HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(
            ok=True,
            service="browser-session-hub",
            version=__version__,
        )

    @app.get("/api/dependencies")
    async def dependencies():
        return {
            "dependencies": [
                dep.model_dump()
                for dep in manager.dependency_status()
            ]
        }

    @app.get("/api/sessions", response_model=SessionListResponse)
    async def list_sessions() -> SessionListResponse:
        sessions = await run_in_threadpool(manager.list_sessions)
        return SessionListResponse(sessions=sessions)

    @app.post(
        "/api/sessions",
        response_model=CreateSessionResponse,
        responses={400: {"model": ErrorResponse}},
    )
    async def create_session(
        request: CreateSessionRequest,
    ) -> CreateSessionResponse:
        try:
            session = await run_in_threadpool(manager.create_session, request)
        except SessionManagerError as exc:
            raise _http_error(exc) from exc
        return CreateSessionResponse(session=session)

    @app.get(
        "/api/sessions/{session_id}",
        response_model=SessionSummary,
        responses={400: {"model": ErrorResponse}},
    )
    async def get_session(session_id: str) -> SessionSummary:
        try:
            return await run_in_threadpool(manager.get_session, session_id)
        except SessionManagerError as exc:
            raise _http_error(exc) from exc

    @app.post(
        "/api/sessions/{session_id}/touch",
        response_model=SessionSummary,
        responses={400: {"model": ErrorResponse}},
    )
    async def touch_session(session_id: str) -> SessionSummary:
        try:
            return await run_in_threadpool(manager.touch_session, session_id)
        except SessionManagerError as exc:
            raise _http_error(exc) from exc

    @app.delete(
        "/api/sessions/{session_id}",
        response_model=SessionSummary,
        responses={400: {"model": ErrorResponse}},
    )
    async def stop_session(session_id: str) -> SessionSummary:
        try:
            return await run_in_threadpool(manager.stop_session, session_id)
        except SessionManagerError as exc:
            raise _http_error(exc) from exc

    static_dir = Path(__file__).parent / "static"

    @app.get("/preview/{session_id}", include_in_schema=False)
    async def preview(session_id: str) -> HTMLResponse:
        try:
            session = await run_in_threadpool(manager.get_session, session_id)
        except SessionManagerError as exc:
            raise _http_error(exc) from exc

        raw_preview_url = _build_raw_preview_url(cfg, session)
        title = escape(f"Preview {session.session_id}")
        iframe_src = escape(raw_preview_url, quote=True)
        vw = session.viewport_width
        vh = session.viewport_height
        html = f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{title}</title>
    <style>
      * {{ box-sizing: border-box; }}
      html, body {{
        margin: 0;
        width: 100%;
        height: 100%;
        overflow: hidden;
        background: #fff;
      }}
      iframe {{
        position: absolute;
        top: 0;
        left: 0;
        width: {vw}px;
        height: {vh}px;
        border: 0;
        transform-origin: top left;
        background: #fff;
      }}
    </style>
  </head>
  <body>
    <iframe src="{iframe_src}" title="{title}" allowfullscreen></iframe>
    <script>
      (function() {{
        var iframe = document.querySelector('iframe');
        function fit() {{
          var sx = window.innerWidth / {vw};
          var sy = window.innerHeight / {vh};
          iframe.style.transform = 'scale(' + sx + ',' + sy + ')';
        }}
        window.addEventListener('resize', fit);
        fit();
      }})();
    </script>
  </body>
</html>
"""
        return HTMLResponse(html)

    @app.get("/", include_in_schema=False)
    async def root() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    return app
