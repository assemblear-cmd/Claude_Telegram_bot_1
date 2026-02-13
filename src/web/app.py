"""FastAPI web application factory."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.web.routes import api, dashboard, sources

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def create_web_app(
    orchestrator: Any,
    session_factory: Any,
    scheduler_service: Any = None,
) -> FastAPI:
    """Create and configure the FastAPI web application."""
    app = FastAPI(
        title="Telegram MultiAgent Publisher",
        description="Web dashboard for managing auto-posting pipeline",
    )

    # Mount static files
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Set up templates
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    # Store shared dependencies
    app.state.orchestrator = orchestrator
    app.state.session_factory = session_factory
    app.state.scheduler_service = scheduler_service
    app.state.templates = templates

    # Include routers
    app.include_router(dashboard.router)
    app.include_router(api.router)
    app.include_router(sources.router)

    logger.info("Web app created")
    return app
