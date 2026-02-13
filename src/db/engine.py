"""Async database engine and session factory."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Base

logger = logging.getLogger(__name__)

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db(database_url: str) -> async_sessionmaker[AsyncSession]:
    """Initialize database engine, create tables, and return session factory."""
    global _engine, _session_factory

    db_path = database_url.replace("sqlite+aiosqlite:///", "")
    if db_path and not db_path.startswith(":"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    _engine = create_async_engine(
        database_url,
        echo=False,
        connect_args={"check_same_thread": False},
    )

    # Enable WAL mode for better concurrent read performance
    async with _engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        await conn.run_sync(Base.metadata.create_all)

    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    logger.info("Database initialized: %s", database_url)
    return _session_factory


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get the session factory (must call init_db first)."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _session_factory


async def close_db() -> None:
    """Close the database engine."""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Database connection closed")
