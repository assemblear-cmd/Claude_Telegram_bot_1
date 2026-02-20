"""Database repository for the Agency42 module."""

from __future__ import annotations

import random
from datetime import datetime
from typing import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.agency.models import AgencyModel, AgencyPost, AgencySettings, ScrapedMedia


# ── AgencyModel CRUD ──────────────────────────────────────────────────

async def get_model(session: AsyncSession, model_id: int) -> AgencyModel | None:
    return await session.get(AgencyModel, model_id)


async def get_model_by_username(session: AsyncSession, username: str) -> AgencyModel | None:
    stmt = select(AgencyModel).where(AgencyModel.username == username)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_models(
    session: AsyncSession, *, active_only: bool = False
) -> Sequence[AgencyModel]:
    stmt = select(AgencyModel).order_by(AgencyModel.username)
    if active_only:
        stmt = stmt.where(AgencyModel.is_active.is_(True))
    result = await session.execute(stmt)
    return result.scalars().all()


async def create_model(session: AsyncSession, **fields) -> AgencyModel:
    obj = AgencyModel(**fields)
    session.add(obj)
    await session.flush()
    return obj


async def update_model(session: AsyncSession, model_id: int, **fields) -> AgencyModel | None:
    stmt = update(AgencyModel).where(AgencyModel.id == model_id).values(**fields)
    await session.execute(stmt)
    await session.flush()
    return await get_model(session, model_id)


async def delete_model(session: AsyncSession, model_id: int) -> bool:
    obj = await get_model(session, model_id)
    if obj:
        await session.delete(obj)
        await session.flush()
        return True
    return False


# ── ScrapedMedia CRUD ─────────────────────────────────────────────────

async def get_media(session: AsyncSession, media_id: int) -> ScrapedMedia | None:
    stmt = select(ScrapedMedia).options(selectinload(ScrapedMedia.model)).where(
        ScrapedMedia.id == media_id
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_media_by_instagram_pk(
    session: AsyncSession, instagram_media_pk: str
) -> ScrapedMedia | None:
    stmt = select(ScrapedMedia).where(
        ScrapedMedia.instagram_media_pk == instagram_media_pk
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_media(
    session: AsyncSession,
    *,
    model_id: int | None = None,
    suitable_only: bool = False,
    unposted_only: bool = False,
    queued_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> Sequence[ScrapedMedia]:
    stmt = (
        select(ScrapedMedia)
        .options(selectinload(ScrapedMedia.model))
        .order_by(ScrapedMedia.scraped_at.desc())
    )
    if model_id is not None:
        stmt = stmt.where(ScrapedMedia.model_id == model_id)
    if suitable_only:
        stmt = stmt.where(ScrapedMedia.is_suitable.is_(True))
    if unposted_only:
        stmt = stmt.where(
            ScrapedMedia.is_posted.is_(False),
            ScrapedMedia.is_rejected.is_(False),
        )
    if queued_only:
        stmt = stmt.where(ScrapedMedia.is_queued.is_(True))
    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()


async def create_media(session: AsyncSession, **fields) -> ScrapedMedia:
    obj = ScrapedMedia(**fields)
    session.add(obj)
    await session.flush()
    return obj


async def update_media(session: AsyncSession, media_id: int, **fields) -> ScrapedMedia | None:
    stmt = update(ScrapedMedia).where(ScrapedMedia.id == media_id).values(**fields)
    await session.execute(stmt)
    await session.flush()
    return await get_media(session, media_id)


async def pick_random_suitable_media(session: AsyncSession) -> ScrapedMedia | None:
    """Pick a random suitable, unposted photo for the next agency post."""
    stmt = (
        select(ScrapedMedia)
        .options(selectinload(ScrapedMedia.model))
        .where(
            ScrapedMedia.is_suitable.is_(True),
            ScrapedMedia.is_posted.is_(False),
            ScrapedMedia.is_rejected.is_(False),
        )
    )
    result = await session.execute(stmt)
    candidates = list(result.scalars().all())
    if not candidates:
        return None
    return random.choice(candidates)


async def count_media(
    session: AsyncSession, *, model_id: int | None = None, suitable_only: bool = False
) -> int:
    stmt = select(func.count(ScrapedMedia.id))
    if model_id is not None:
        stmt = stmt.where(ScrapedMedia.model_id == model_id)
    if suitable_only:
        stmt = stmt.where(ScrapedMedia.is_suitable.is_(True))
    result = await session.execute(stmt)
    return result.scalar_one()


# ── AgencyPost CRUD ───────────────────────────────────────────────────

async def get_post(session: AsyncSession, post_id: int) -> AgencyPost | None:
    stmt = (
        select(AgencyPost)
        .options(selectinload(AgencyPost.media).selectinload(ScrapedMedia.model))
        .where(AgencyPost.id == post_id)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_posts(
    session: AsyncSession, *, status: str | None = None, limit: int = 50
) -> Sequence[AgencyPost]:
    stmt = (
        select(AgencyPost)
        .options(selectinload(AgencyPost.media).selectinload(ScrapedMedia.model))
        .order_by(AgencyPost.created_at.desc())
        .limit(limit)
    )
    if status:
        stmt = stmt.where(AgencyPost.status == status)
    result = await session.execute(stmt)
    return result.scalars().all()


async def create_post(session: AsyncSession, **fields) -> AgencyPost:
    obj = AgencyPost(**fields)
    session.add(obj)
    await session.flush()
    return obj


async def update_post(session: AsyncSession, post_id: int, **fields) -> AgencyPost | None:
    stmt = update(AgencyPost).where(AgencyPost.id == post_id).values(**fields)
    await session.execute(stmt)
    await session.flush()
    return await get_post(session, post_id)


async def count_posts_today(session: AsyncSession) -> int:
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = select(func.count(AgencyPost.id)).where(
        AgencyPost.status == "published",
        AgencyPost.published_at >= today_start,
    )
    result = await session.execute(stmt)
    return result.scalar_one()


# ── AgencySettings ────────────────────────────────────────────────────

async def get_settings(session: AsyncSession) -> AgencySettings:
    obj = await session.get(AgencySettings, 1)
    if obj is None:
        obj = AgencySettings(id=1)
        session.add(obj)
        await session.flush()
    return obj


async def update_settings(session: AsyncSession, **fields) -> AgencySettings:
    settings = await get_settings(session)
    for key, value in fields.items():
        setattr(settings, key, value)
    await session.flush()
    return settings
