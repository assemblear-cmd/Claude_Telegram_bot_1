"""FastAPI web application factory."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.agency.web.routes import router as agency_router
from src.web.routes import api, dashboard, sources

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
MEDIA_DIR = Path("data/agency/photos")


def create_web_app(
    orchestrator: Any,
    session_factory: Any,
    scheduler_service: Any = None,
    agency_scheduler: Any = None,
) -> FastAPI:
    """Create and configure the FastAPI web application."""
    app = FastAPI(
        title="Agency42 — Model Agency Platform",
        description="Admin dashboard for model agency Instagram auto-posting",
    )

    # Mount static files
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Mount agency media directory for serving scraped photos
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    # Set up templates
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    # Store shared dependencies
    app.state.orchestrator = orchestrator
    app.state.session_factory = session_factory
    app.state.scheduler_service = scheduler_service
    app.state.agency_scheduler = agency_scheduler
    app.state.templates = templates

    # Include routers
    app.include_router(dashboard.router)
    app.include_router(api.router)
    app.include_router(sources.router)
    app.include_router(agency_router)

    # Media serving endpoint for agency photos
    @app.get("/agency/media/{media_id}")
    async def serve_agency_media(media_id: int):
        from fastapi.responses import FileResponse
        from src.agency import repository as repo

        async with session_factory() as session:
            media = await repo.get_media(session, media_id)
            if media and media.local_path:
                media_path = Path(media.local_path)
                if media_path.exists():
                    return FileResponse(str(media_path))
        from fastapi.responses import Response
        return Response(status_code=404)

    logger.info("Web app created with Agency42 module")
    return app
