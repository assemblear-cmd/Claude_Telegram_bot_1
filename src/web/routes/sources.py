"""Source management routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from src.db.models import Source
from src.db import repository as repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("")
async def sources_page(request: Request):
    """List all sources."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        stmt = select(Source).order_by(Source.trust_score.desc())
        result = await session.execute(stmt)
        sources = result.scalars().all()

    return request.app.state.templates.TemplateResponse(
        "sources.html",
        {"request": request, "sources": sources},
    )


@router.post("/{source_id}/toggle-whitelist")
async def toggle_whitelist(request: Request, source_id: int):
    """Toggle source whitelist status."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        source = await session.get(Source, source_id)
        if source:
            source.is_whitelisted = not source.is_whitelisted
            await session.commit()

    return RedirectResponse(url="/sources", status_code=303)


@router.post("/add")
async def add_source(
    request: Request,
    url: str = Form(...),
    topic: str = Form(...),
    title: str = Form(""),
):
    """Manually add a source."""
    from src.utils.text import extract_domain

    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        source = Source(
            url=url,
            domain=extract_domain(url),
            title=title or extract_domain(url),
            topic=topic,
            trust_score=0.8,
            is_whitelisted=True,
        )
        session.add(source)
        await session.commit()

    return RedirectResponse(url="/sources", status_code=303)
