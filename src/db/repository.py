"""Generic async CRUD repository helpers."""

from __future__ import annotations

from typing import Any, Sequence, TypeVar

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Base

T = TypeVar("T", bound=Base)


async def get_by_id(session: AsyncSession, model: type[T], id_: int) -> T | None:
    return await session.get(model, id_)


async def create(session: AsyncSession, obj: Base) -> Base:
    session.add(obj)
    await session.flush()
    return obj


async def update_fields(
    session: AsyncSession, model: type[T], id_: int, **fields: Any
) -> T | None:
    stmt = update(model).where(model.id == id_).values(**fields)
    await session.execute(stmt)
    await session.flush()
    return await get_by_id(session, model, id_)


async def list_all(
    session: AsyncSession, model: type[T], **filters: Any
) -> Sequence[T]:
    stmt = select(model)
    for key, value in filters.items():
        stmt = stmt.where(getattr(model, key) == value)
    result = await session.execute(stmt)
    return result.scalars().all()


async def list_ordered(
    session: AsyncSession,
    model: type[T],
    order_by: Any = None,
    limit: int | None = None,
    **filters: Any,
) -> Sequence[T]:
    stmt = select(model)
    for key, value in filters.items():
        stmt = stmt.where(getattr(model, key) == value)
    if order_by is not None:
        stmt = stmt.order_by(order_by)
    if limit:
        stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()


async def delete_by_id(session: AsyncSession, model: type[T], id_: int) -> bool:
    obj = await get_by_id(session, model, id_)
    if obj:
        await session.delete(obj)
        await session.flush()
        return True
    return False
