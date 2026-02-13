"""YouTube transcript extraction service."""

from __future__ import annotations

import logging
import re

from youtube_transcript_api import YouTubeTranscriptApi

from src.utils.text import clean_text

logger = logging.getLogger(__name__)


def extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from various URL formats."""
    patterns = [
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


class YouTubeTranscriptService:
    """Fetch transcripts from YouTube videos."""

    async def get_transcript(
        self, url: str, languages: list[str] | None = None
    ) -> str:
        """Get transcript for a YouTube video URL."""
        video_id = extract_video_id(url)
        if not video_id:
            raise ValueError(f"Could not extract video ID from: {url}")

        langs = languages or ["ru", "en"]

        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            transcript = transcript_list.find_transcript(langs)
            fetched = transcript.fetch()
        except Exception:
            # Try auto-generated transcripts
            fetched = YouTubeTranscriptApi.get_transcript(video_id, languages=langs)

        text = " ".join(entry["text"] for entry in fetched)
        text = clean_text(text)
        logger.info(
            "YouTube transcript for %s: %d chars", video_id, len(text)
        )
        return text
