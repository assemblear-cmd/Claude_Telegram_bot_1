"""Agency42 admin panel web routes."""

from __future__ import annotations

import logging
import re
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from src.agency import repository as repo
from src.agency.models import AgencyModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agency", tags=["agency"])


def _extract_username(url_or_username: str) -> str:
    """Extract Instagram username from URL or return as-is."""
    url_or_username = url_or_username.strip().rstrip("/")
    # Strip query params (like ?igsh=...)
    url_or_username = url_or_username.split("?")[0]
    match = re.search(r"instagram\.com/([A-Za-z0-9_.]+)", url_or_username)
    if match:
        return match.group(1)
    return url_or_username


# ── Dashboard ─────────────────────────────────────────────────────────

@router.get("/")
async def agency_dashboard(request: Request):
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        models = await repo.list_models(session)
        settings = await repo.get_settings(session)
        total_photos = await repo.count_media(session)
        suitable_photos = await repo.count_media(session, suitable_only=True)
        recent_posts = await repo.list_posts(session, limit=10)
        posts_today = await repo.count_posts_today(session)

    return request.app.state.templates.TemplateResponse(
        "agency/dashboard.html",
        {
            "request": request,
            "models": models,
            "settings": settings,
            "total_photos": total_photos,
            "suitable_photos": suitable_photos,
            "recent_posts": recent_posts,
            "posts_today": posts_today,
        },
    )


# ── Models management ─────────────────────────────────────────────────

@router.get("/models")
async def models_page(request: Request):
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        models = await repo.list_models(session)
    return request.app.state.templates.TemplateResponse(
        "agency/models.html",
        {"request": request, "models": models},
    )


@router.post("/models/add")
async def add_model(request: Request):
    form = await request.form()
    instagram_url = str(form.get("instagram_url", ""))
    username = _extract_username(instagram_url)

    if not username:
        return RedirectResponse("/agency/models?error=invalid_url", status_code=303)

    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        existing = await repo.get_model_by_username(session, username)
        if existing:
            return RedirectResponse("/agency/models?error=duplicate", status_code=303)

        # Try to fetch profile info
        full_name = str(form.get("full_name", "")) or None
        profile_pic_url = None
        ig_pk = None

        agency_scheduler = getattr(request.app.state, "agency_scheduler", None)
        if agency_scheduler:
            info = agency_scheduler._scraper.get_user_info(username)
            if info:
                full_name = full_name or info.get("full_name")
                profile_pic_url = info.get("profile_pic_url")
                ig_pk = info.get("pk")

        if not instagram_url.startswith("http"):
            instagram_url = f"https://www.instagram.com/{username}/"

        await repo.create_model(
            session,
            username=username,
            full_name=full_name,
            instagram_url=instagram_url,
            profile_pic_url=profile_pic_url,
            instagram_pk=ig_pk,
        )
        await session.commit()

    return RedirectResponse("/agency/models", status_code=303)


@router.post("/models/{model_id}/toggle")
async def toggle_model(request: Request, model_id: int):
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        model = await repo.get_model(session, model_id)
        if model:
            await repo.update_model(session, model_id, is_active=not model.is_active)
            await session.commit()
    return RedirectResponse("/agency/models", status_code=303)


@router.post("/models/{model_id}/delete")
async def delete_model(request: Request, model_id: int):
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        await repo.delete_model(session, model_id)
        await session.commit()
    return RedirectResponse("/agency/models", status_code=303)


@router.post("/models/{model_id}/scrape")
async def scrape_model(request: Request, model_id: int):
    scheduler = getattr(request.app.state, "agency_scheduler", None)
    if scheduler:
        count = await scheduler.trigger_scrape_model(model_id)
        return RedirectResponse(f"/agency/models?scraped={count}", status_code=303)
    return RedirectResponse("/agency/models?error=no_scheduler", status_code=303)


# ── Photos library ────────────────────────────────────────────────────

@router.get("/photos")
async def photos_page(request: Request):
    model_id = request.query_params.get("model_id")
    suitable = request.query_params.get("suitable") == "1"
    unposted = request.query_params.get("unposted") == "1"
    page = int(request.query_params.get("page", "1"))
    per_page = 24

    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        media_list = await repo.list_media(
            session,
            model_id=int(model_id) if model_id else None,
            suitable_only=suitable,
            unposted_only=unposted,
            limit=per_page,
            offset=(page - 1) * per_page,
        )
        models = await repo.list_models(session)

    return request.app.state.templates.TemplateResponse(
        "agency/photos.html",
        {
            "request": request,
            "media_list": media_list,
            "models": models,
            "current_model_id": model_id,
            "suitable_filter": suitable,
            "unposted_filter": unposted,
            "page": page,
        },
    )


@router.post("/photos/{media_id}/approve")
async def approve_photo(request: Request, media_id: int):
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        await repo.update_media(session, media_id, is_suitable=True, is_rejected=False)
        await session.commit()
    return RedirectResponse("/agency/photos", status_code=303)


@router.post("/photos/{media_id}/reject")
async def reject_photo(request: Request, media_id: int):
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        await repo.update_media(session, media_id, is_suitable=False, is_rejected=True)
        await session.commit()
    return RedirectResponse("/agency/photos", status_code=303)


@router.post("/photos/{media_id}/queue")
async def queue_photo(request: Request, media_id: int):
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        await repo.update_media(session, media_id, is_queued=True)
        await session.commit()
    return RedirectResponse("/agency/photos", status_code=303)


# ── Queue / Post history ──────────────────────────────────────────────

@router.get("/queue")
async def queue_page(request: Request):
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        queued_media = await repo.list_media(session, queued_only=True, limit=50)
        recent_posts = await repo.list_posts(session, limit=50)
    return request.app.state.templates.TemplateResponse(
        "agency/queue.html",
        {
            "request": request,
            "queued_media": queued_media,
            "recent_posts": recent_posts,
        },
    )


@router.post("/queue/post-next")
async def post_next(request: Request):
    scheduler = getattr(request.app.state, "agency_scheduler", None)
    if scheduler:
        post_id = await scheduler.trigger_post()
        return RedirectResponse(
            f"/agency/queue?posted={post_id}" if post_id else "/agency/queue?error=no_media",
            status_code=303,
        )
    return RedirectResponse("/agency/queue?error=no_scheduler", status_code=303)


# ── Settings ──────────────────────────────────────────────────────────

@router.get("/settings")
async def settings_page(request: Request):
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        settings = await repo.get_settings(session)
    return request.app.state.templates.TemplateResponse(
        "agency/settings.html",
        {"request": request, "settings": settings},
    )


@router.post("/settings")
async def update_settings(request: Request):
    form = await request.form()
    fields = {
        "agency_instagram_username": str(form.get("agency_instagram_username", "natagiarl")),
        "posting_interval_minutes": int(form.get("posting_interval_minutes", 180)),
        "caption_template": str(form.get("caption_template", "")),
        "watermark_text": str(form.get("watermark_text", "@natagiarl")),
        "auto_posting_enabled": form.get("auto_posting_enabled") == "on",
        "auto_scrape_enabled": form.get("auto_scrape_enabled") == "on",
        "max_posts_per_day": int(form.get("max_posts_per_day", 8)),
        "scrape_interval_minutes": int(form.get("scrape_interval_minutes", 360)),
    }

    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        await repo.update_settings(session, **fields)
        await session.commit()

    # Reschedule if scheduler is available
    scheduler = getattr(request.app.state, "agency_scheduler", None)
    if scheduler:
        await scheduler.reschedule()

    return RedirectResponse("/agency/settings?saved=1", status_code=303)


# ── API endpoints ─────────────────────────────────────────────────────

@router.post("/api/scrape-all")
async def api_scrape_all(request: Request):
    scheduler = getattr(request.app.state, "agency_scheduler", None)
    if not scheduler:
        return JSONResponse({"error": "Scheduler not available"}, status_code=503)
    results = await scheduler.trigger_scrape_all()
    return JSONResponse({"results": results, "total_new": sum(results.values())})


@router.post("/api/analyze")
async def api_analyze(request: Request):
    scheduler = getattr(request.app.state, "agency_scheduler", None)
    if not scheduler:
        return JSONResponse({"error": "Scheduler not available"}, status_code=503)
    count = await scheduler.trigger_analyze()
    return JSONResponse({"analyzed": count})


@router.get("/api/stats")
async def api_stats(request: Request):
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        models = await repo.list_models(session)
        total = await repo.count_media(session)
        suitable = await repo.count_media(session, suitable_only=True)
        posts_today = await repo.count_posts_today(session)
        settings = await repo.get_settings(session)
    return JSONResponse({
        "models_count": len(models),
        "active_models": sum(1 for m in models if m.is_active),
        "total_photos": total,
        "suitable_photos": suitable,
        "posts_today": posts_today,
        "auto_posting": settings.auto_posting_enabled,
        "auto_scraping": settings.auto_scrape_enabled,
    })
