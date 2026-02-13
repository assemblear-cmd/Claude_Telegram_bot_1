"""Retry decorators using tenacity."""

from __future__ import annotations

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


def with_retry(
    max_attempts: int = 3,
    min_wait: float = 1,
    max_wait: float = 30,
    retry_on: tuple[type[Exception], ...] = (Exception,),
):
    """Decorator: retry with exponential backoff."""
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
        retry=retry_if_exception_type(retry_on),
        reraise=True,
    )
