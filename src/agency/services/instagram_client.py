"""Instagram client wrapper using instagrapi."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from instagrapi import Client
from instagrapi.types import Media, Story, UserShort

logger = logging.getLogger(__name__)


class InstagramClient:
    """Wraps instagrapi.Client for session management and common operations."""

    def __init__(
        self,
        username: str,
        password: str,
        session_path: Path | None = None,
    ) -> None:
        self._username = username
        self._password = password
        self._session_path = session_path or Path("data/agency/ig_session.json")
        self._client = Client()
        self._client.delay_range = [2, 5]  # anti-spam delay between requests
        self._logged_in = False

    @property
    def client(self) -> Client:
        return self._client

    async def login(self) -> bool:
        """Log in to Instagram (loads saved session if available)."""
        if self._logged_in:
            return True
        try:
            self._session_path.parent.mkdir(parents=True, exist_ok=True)
            if self._session_path.exists():
                self._client.load_settings(self._session_path)
                self._client.login(self._username, self._password)
                logger.info("Logged in with saved session for @%s", self._username)
            else:
                self._client.login(self._username, self._password)
                self._client.dump_settings(self._session_path)
                logger.info("Fresh login for @%s, session saved", self._username)
            self._logged_in = True
            return True
        except Exception:
            logger.exception("Instagram login failed for @%s", self._username)
            return False

    def get_user_info(self, username: str) -> dict[str, Any] | None:
        """Get public profile info for a username."""
        try:
            user_id = self._client.user_id_from_username(username)
            info = self._client.user_info(user_id)
            return {
                "pk": str(info.pk),
                "username": info.username,
                "full_name": info.full_name,
                "profile_pic_url": str(info.profile_pic_url),
                "media_count": info.media_count,
                "follower_count": info.follower_count,
            }
        except Exception:
            logger.exception("Failed to get user info for @%s", username)
            return None

    def get_user_medias(self, username: str, amount: int = 20) -> list[Media]:
        """Fetch recent media posts from a user's profile."""
        try:
            user_id = self._client.user_id_from_username(username)
            return self._client.user_medias(user_id, amount=amount)
        except Exception:
            logger.exception("Failed to get medias for @%s", username)
            return []

    def get_user_stories(self, username: str) -> list[Story]:
        """Fetch current stories from a user."""
        try:
            user_id = self._client.user_id_from_username(username)
            return self._client.user_stories(user_id)
        except Exception:
            logger.exception("Failed to get stories for @%s", username)
            return []

    def download_media(self, media_pk: str, dest_dir: Path) -> Path | None:
        """Download a media item (photo) to local storage."""
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            path = self._client.photo_download(int(media_pk), folder=dest_dir)
            logger.info("Downloaded media %s → %s", media_pk, path)
            return Path(path)
        except Exception:
            logger.exception("Failed to download media pk=%s", media_pk)
            return None

    def download_story(self, story_pk: str, dest_dir: Path) -> Path | None:
        """Download a story to local storage."""
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            path = self._client.story_download(int(story_pk), folder=dest_dir)
            logger.info("Downloaded story %s → %s", story_pk, path)
            return Path(path)
        except Exception:
            logger.exception("Failed to download story pk=%s", story_pk)
            return None

    def upload_photo(
        self,
        photo_path: Path,
        caption: str,
    ) -> Media | None:
        """Upload a photo to the agency's Instagram account."""
        try:
            media = self._client.photo_upload(str(photo_path), caption=caption)
            logger.info("Uploaded photo → media pk=%s", media.pk)
            return media
        except Exception:
            logger.exception("Failed to upload photo %s", photo_path)
            return None

    def upload_story(self, photo_path: Path) -> Story | None:
        """Upload a photo as a story."""
        try:
            story = self._client.photo_upload_to_story(str(photo_path))
            logger.info("Uploaded story → pk=%s", story.pk)
            return story
        except Exception:
            logger.exception("Failed to upload story %s", photo_path)
            return None
