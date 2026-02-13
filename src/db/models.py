"""SQLAlchemy ORM models for all database tables."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(Text)
    topic: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    trust_score: Mapped[float] = mapped_column(Float, default=0.5)
    is_whitelisted: Mapped[bool] = mapped_column(Boolean, default=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    materials: Mapped[list[RawMaterial]] = relationship(back_populates="source")


class RawMaterial(Base):
    __tablename__ = "raw_materials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("sources.id"), nullable=True
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(50), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    source: Mapped[Source | None] = relationship(back_populates="materials")
    post_sources: Mapped[list[PostSource]] = relationship(back_populates="material")


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    pipeline_state: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    concept_bullet: Mapped[str | None] = mapped_column(Text)
    draft_text: Mapped[str | None] = mapped_column(Text)
    formatted_text: Mapped[str | None] = mapped_column(Text)
    final_text: Mapped[str | None] = mapped_column(Text)
    fact_check_score: Mapped[float | None] = mapped_column(Float)
    fact_check_notes: Mapped[str | None] = mapped_column(Text)
    admin_notes: Mapped[str | None] = mapped_column(Text)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    telegram_message_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    post_sources: Mapped[list[PostSource]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )
    post_links: Mapped[list[PostLink]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )
    pipeline_events: Mapped[list[PipelineEvent]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )


class PostSource(Base):
    __tablename__ = "post_sources"
    __table_args__ = (UniqueConstraint("post_id", "material_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(Integer, ForeignKey("posts.id"), nullable=False)
    material_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("raw_materials.id"), nullable=False
    )
    relevance_score: Mapped[float | None] = mapped_column(Float)

    post: Mapped[Post] = relationship(back_populates="post_sources")
    material: Mapped[RawMaterial] = relationship(back_populates="post_sources")


class PostLink(Base):
    __tablename__ = "post_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(Integer, ForeignKey("posts.id"), nullable=False)
    keyword: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    inserted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    post: Mapped[Post] = relationship(back_populates="post_links")


class ScheduleSlot(Base):
    __tablename__ = "schedule_slots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    time_utc: Mapped[str] = mapped_column(String(5), nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)


class PipelineEvent(Base):
    __tablename__ = "pipeline_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("posts.id"), nullable=False, index=True
    )
    from_state: Mapped[str | None] = mapped_column(String(50))
    to_state: Mapped[str] = mapped_column(String(50), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    details: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    post: Mapped[Post] = relationship(back_populates="pipeline_events")
