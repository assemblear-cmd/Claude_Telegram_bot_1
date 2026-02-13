"""Dashboard routes: post listing and details."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from sqlalchemy import select

from src.db.models import PipelineEvent, Post, PostLink, PostSource, RawMaterial
from src.orchestrator.state import PipelineState

logger = logging.getLogger(__name__)

router = APIRouter(tags=["dashboard"])


@router.get("/")
async def index(request: Request):
    """Redirect to dashboard."""
    return request.app.state.templates.TemplateResponse(
        "dashboard.html",
        await _dashboard_context(request),
    )


@router.get("/dashboard")
async def dashboard_page(request: Request):
    """Main dashboard: list all posts."""
    return request.app.state.templates.TemplateResponse(
        "dashboard.html",
        await _dashboard_context(request),
    )


@router.get("/posts/{post_id}")
async def post_detail(request: Request, post_id: int):
    """Post detail page."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        post = await session.get(Post, post_id)
        if not post:
            return request.app.state.templates.TemplateResponse(
                "dashboard.html",
                {"request": request, "posts": [], "error": "Post not found"},
            )

        # Load pipeline events
        events_stmt = (
            select(PipelineEvent)
            .where(PipelineEvent.post_id == post_id)
            .order_by(PipelineEvent.created_at.desc())
        )
        events_result = await session.execute(events_stmt)
        events = events_result.scalars().all()

        # Load links
        links_stmt = select(PostLink).where(PostLink.post_id == post_id)
        links_result = await session.execute(links_stmt)
        links = links_result.scalars().all()

        # Load source materials
        materials_stmt = (
            select(RawMaterial)
            .join(PostSource, PostSource.material_id == RawMaterial.id)
            .where(PostSource.post_id == post_id)
        )
        materials_result = await session.execute(materials_stmt)
        materials = materials_result.scalars().all()

    is_reviewable = post.pipeline_state == PipelineState.PENDING_REVIEW.value

    return request.app.state.templates.TemplateResponse(
        "post_detail.html",
        {
            "request": request,
            "post": post,
            "events": events,
            "links": links,
            "materials": materials,
            "is_reviewable": is_reviewable,
        },
    )


@router.get("/schedule")
async def schedule_page(request: Request):
    """Show upcoming scheduled posts."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        stmt = (
            select(Post)
            .where(Post.pipeline_state.in_(["scheduled", "publishing", "published"]))
            .order_by(Post.scheduled_at)
        )
        result = await session.execute(stmt)
        posts = result.scalars().all()

    return request.app.state.templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "posts": posts,
            "page_title": "Schedule",
            "filter_state": "scheduled",
        },
    )


async def _dashboard_context(request: Request) -> dict:
    """Build context for the dashboard page."""
    session_factory = request.app.state.session_factory
    state_filter = request.query_params.get("state")

    async with session_factory() as session:
        stmt = select(Post).order_by(Post.created_at.desc()).limit(50)
        if state_filter:
            stmt = stmt.where(Post.pipeline_state == state_filter)
        result = await session.execute(stmt)
        posts = result.scalars().all()

    return {
        "request": request,
        "posts": posts,
        "page_title": "Dashboard",
        "filter_state": state_filter,
        "all_states": [s.value for s in PipelineState],
    }
