"""SQLAlchemy ORM models for the Agency42 module."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.models import Base


class AgencyModel(Base):
    """An Instagram model whose content we scrape and repost."""

    __tablename__ = "agency_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str | None] = mapped_column(String(500))
    instagram_url: Mapped[str] = mapped_column(Text, nullable=False)
    profile_pic_url: Mapped[str | None] = mapped_column(Text)
    instagram_pk: Mapped[str | None] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime)
    scrape_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    photos: Mapped[list[ScrapedMedia]] = relationship(back_populates="model", cascade="all, delete-orphan")


class ScrapedMedia(Base):
    """A photo or story scraped from a model's Instagram account."""

    __tablename__ = "agency_scraped_media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agency_models.id"), nullable=False, index=True
    )
    instagram_media_pk: Mapped[str | None] = mapped_column(String(100), unique=True)
    media_type: Mapped[str] = mapped_column(String(20), nullable=False)  # "photo" or "story"
    media_url: Mapped[str] = mapped_column(Text, nullable=False)
    local_path: Mapped[str | None] = mapped_column(Text)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    caption: Mapped[str | None] = mapped_column(Text)

    # Analysis results
    is_suitable: Mapped[bool | None] = mapped_column(Boolean)
    analysis_score: Mapped[float | None] = mapped_column(Float)
    analysis_notes: Mapped[str | None] = mapped_column(Text)
    person_count: Mapped[int | None] = mapped_column(Integer)
    face_visible: Mapped[bool | None] = mapped_column(Boolean)
    body_visible: Mapped[bool | None] = mapped_column(Boolean)

    # Status
    is_posted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_queued: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_rejected: Mapped[bool] = mapped_column(Boolean, default=False)

    scraped_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    model: Mapped[AgencyModel] = relationship(back_populates="photos")
    posts: Mapped[list[AgencyPost]] = relationship(back_populates="media")


class AgencyPost(Base):
    """A post published to the agency's Instagram account."""

    __tablename__ = "agency_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    media_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agency_scraped_media.id"), nullable=False
    )
    caption: Mapped[str | None] = mapped_column(Text)
    instagram_media_pk: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True
    )  # pending, publishing, published, failed
    error_message: Mapped[str | None] = mapped_column(Text)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    media: Mapped[ScrapedMedia] = relationship(back_populates="posts")


class AgencySettings(Base):
    """Singleton row storing agency configuration."""

    __tablename__ = "agency_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    agency_instagram_username: Mapped[str] = mapped_column(
        String(255), default="natagiarl"
    )
    posting_interval_minutes: Mapped[int] = mapped_column(Integer, default=180)
    caption_template: Mapped[str] = mapped_column(
        Text,
        default=(
            "Follow @{model_username} | Represented by @natagiarl\n"
            "\n"
            "#model #agency #natagiarl #fashion"
        ),
    )
    watermark_text: Mapped[str] = mapped_column(String(255), default="@natagiarl")
    auto_posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    max_posts_per_day: Mapped[int] = mapped_column(Integer, default=8)
    scrape_interval_minutes: Mapped[int] = mapped_column(Integer, default=360)
    auto_scrape_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
