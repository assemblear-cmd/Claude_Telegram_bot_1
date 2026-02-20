"""Async Google Gemini API wrapper with retry and prompt rendering."""

from __future__ import annotations

import json
import logging
from typing import Any

import google.generativeai as genai

from src.utils.retry import with_retry

logger = logging.getLogger(__name__)


class GeminiClient:
    """Wrapper around Google Gemini with retry, prompt templates, and JSON parsing."""

    def __init__(self, api_key: str, default_model: str = "gemini-2.0-flash"):
        genai.configure(api_key=api_key)
        self.default_model = default_model

    def _get_model(
        self, model: str | None = None, system: str | None = None
    ) -> genai.GenerativeModel:
        return genai.GenerativeModel(
            model_name=model or self.default_model,
            system_instruction=system or None,
        )

    @with_retry(max_attempts=3, min_wait=2, max_wait=30)
    async def complete(
        self,
        prompt: str,
        *,
        model: str | None = None,
        max_tokens: int = 2000,
        system: str | None = None,
        temperature: float = 0.7,
    ) -> str:
        """Send a prompt to Gemini and return the text response."""
        gemini_model = self._get_model(model, system)

        response = await gemini_model.generate_content_async(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )
        text = response.text
        logger.debug(
            "Gemini response: model=%s, prompt_tokens=%s, completion_tokens=%s",
            model or self.default_model,
            getattr(response.usage_metadata, "prompt_token_count", "?"),
            getattr(response.usage_metadata, "candidates_token_count", "?"),
        )
        return text

    async def complete_json(
        self,
        prompt: str,
        *,
        model: str | None = None,
        max_tokens: int = 2000,
        system: str | None = None,
        temperature: float = 0.3,
    ) -> Any:
        """Send a prompt and parse the response as JSON."""
        text = await self.complete(
            prompt,
            model=model,
            max_tokens=max_tokens,
            system=system or "Respond only with valid JSON, no markdown code blocks.",
            temperature=temperature,
        )
        # Strip possible markdown code blocks
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        return json.loads(text)

    def render_prompt(self, template: str, **kwargs: Any) -> str:
        """Render a prompt template with keyword arguments."""
        return template.format(**kwargs)
