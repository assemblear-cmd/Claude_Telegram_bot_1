"""Async Anthropic Claude API wrapper with retry and prompt rendering."""

from __future__ import annotations

import json
import logging
from typing import Any

from anthropic import AsyncAnthropic

from src.utils.retry import with_retry

logger = logging.getLogger(__name__)


class ClaudeClient:
    """Wrapper around AsyncAnthropic with retry, prompt templates, and JSON parsing."""

    def __init__(self, api_key: str, default_model: str = "claude-sonnet-4-5-20250929"):
        self.client = AsyncAnthropic(api_key=api_key)
        self.default_model = default_model

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
        """Send a prompt to Claude and return the text response."""
        messages = [{"role": "user", "content": prompt}]
        kwargs: dict[str, Any] = {
            "model": model or self.default_model,
            "max_tokens": max_tokens,
            "messages": messages,
            "temperature": temperature,
        }
        if system:
            kwargs["system"] = system

        response = await self.client.messages.create(**kwargs)
        text = response.content[0].text
        logger.debug(
            "Claude response: model=%s, tokens=%d/%d",
            response.model,
            response.usage.input_tokens,
            response.usage.output_tokens,
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
