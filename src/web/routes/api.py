"""API routes: approve/reject/edit posts, create new posts."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["api"])


@router.post("/posts/new")
async def create_post(request: Request, topic: str = Form(...)):
    """Create a new post and start the pipeline."""
    orchestrator = request.app.state.orchestrator
    post_id = await orchestrator.create_post(topic)

    import asyncio
    asyncio.create_task(orchestrator.run_full_pipeline(post_id))

    return RedirectResponse(url=f"/posts/{post_id}", status_code=303)


@router.post("/posts/{post_id}/approve")
async def approve_post(request: Request, post_id: int):
    """Approve a post pending review."""
    orchestrator = request.app.state.orchestrator

    import asyncio
    asyncio.create_task(orchestrator.handle_admin_decision(post_id, "approve"))

    return RedirectResponse(url=f"/posts/{post_id}", status_code=303)


@router.post("/posts/{post_id}/reject")
async def reject_post(request: Request, post_id: int):
    """Reject a post."""
    orchestrator = request.app.state.orchestrator
    await orchestrator.handle_admin_decision(post_id, "reject")
    return RedirectResponse(url=f"/posts/{post_id}", status_code=303)


@router.post("/posts/{post_id}/edit")
async def edit_post(request: Request, post_id: int, notes: str = Form(...)):
    """Submit edit feedback and re-run pipeline."""
    orchestrator = request.app.state.orchestrator

    import asyncio
    asyncio.create_task(orchestrator.handle_admin_decision(post_id, "edit", notes))

    return RedirectResponse(url=f"/posts/{post_id}", status_code=303)
