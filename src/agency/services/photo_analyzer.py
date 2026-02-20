"""Photo analysis service using Google Gemini Vision API."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

import google.generativeai as genai
from sqlalchemy.ext.asyncio import AsyncSession

from src.agency import repository as repo
from src.agency.models import ScrapedMedia

logger = logging.getLogger(__name__)

ANALYSIS_PROMPT = """Analyze this photo for a model agency's Instagram repost.

Evaluate the image and respond in JSON format:

{
  "person_count": <number of people visible>,
  "face_visible": <true/false - is a face clearly visible>,
  "body_visible": <true/false - are arms and legs visible/not hidden>,
  "is_suitable": <true/false - suitable for a model agency repost>,
  "score": <0.0 to 1.0 - overall quality score>,
  "notes": "<brief explanation>"
}

Criteria for suitability:
- Exactly 1 person in the photo
- Face is clearly visible (not obscured/covered)
- Arms and legs are visible (open pose, not cropped out)
- Professional/aesthetic quality suitable for a model agency
- No group photos, no text-heavy images, no memes

Return ONLY the JSON object, nothing else."""


class PhotoAnalyzerService:
    """Analyzes photos using Gemini Vision to determine suitability."""

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        genai.configure(api_key=api_key)
        self._model_name = model

    def analyze_image(self, image_path: Path) -> dict | None:
        """Analyze a single image file. Returns parsed analysis dict."""
        if not image_path.exists():
            logger.warning("Image not found: %s", image_path)
            return None

        try:
            image_data = base64.standard_b64encode(image_path.read_bytes()).decode("utf-8")

            suffix = image_path.suffix.lower()
            media_types = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".gif": "image/gif",
                ".webp": "image/webp",
            }
            media_type = media_types.get(suffix, "image/jpeg")

            model = genai.GenerativeModel(self._model_name)
            response = model.generate_content(
                [
                    {"inline_data": {"mime_type": media_type, "data": image_data}},
                    ANALYSIS_PROMPT,
                ],
                generation_config=genai.GenerationConfig(
                    temperature=0.2,
                    max_output_tokens=500,
                ),
            )

            text = response.text.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
                text = text.rsplit("```", 1)[0].strip()
            return json.loads(text)

        except Exception:
            logger.exception("Failed to analyze image %s", image_path)
            return None

    async def analyze_media(self, session: AsyncSession, media: ScrapedMedia) -> bool:
        """Analyze a scraped media item and update its DB record."""
        if not media.local_path:
            logger.warning("No local path for media id=%d", media.id)
            return False

        result = self.analyze_image(Path(media.local_path))
        if result is None:
            return False

        await repo.update_media(
            session,
            media.id,
            person_count=result.get("person_count"),
            face_visible=result.get("face_visible"),
            body_visible=result.get("body_visible"),
            is_suitable=result.get("is_suitable", False),
            analysis_score=result.get("score"),
            analysis_notes=result.get("notes"),
        )
        await session.commit()
        logger.info(
            "Analyzed media id=%d: suitable=%s score=%.2f",
            media.id,
            result.get("is_suitable"),
            result.get("score", 0),
        )
        return True

    async def analyze_unanalyzed(self, session: AsyncSession, limit: int = 20) -> int:
        """Analyze all unanalyzed media items. Returns count of analyzed items."""
        media_list = await repo.list_media(session, limit=limit)
        count = 0
        for media in media_list:
            if media.is_suitable is not None:
                continue  # already analyzed
            if not media.local_path:
                continue
            success = await self.analyze_media(session, media)
            if success:
                count += 1
        return count
