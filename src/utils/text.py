"""Text utilities: cleaning, truncation, Telegram HTML formatting helpers."""

from __future__ import annotations

import html
import re


def clean_text(text: str) -> str:
    """Remove excessive whitespace, normalize newlines."""
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def truncate(text: str, max_length: int = 4096, suffix: str = "...") -> str:
    """Truncate text to max_length, preserving word boundaries."""
    if len(text) <= max_length:
        return text
    truncated = text[: max_length - len(suffix)]
    last_space = truncated.rfind(" ")
    if last_space > max_length // 2:
        truncated = truncated[:last_space]
    return truncated + suffix


def escape_html(text: str) -> str:
    """Escape text for Telegram HTML parse mode."""
    return html.escape(text)


def insert_html_links(text: str, links: list[dict[str, str]]) -> str:
    """Insert HTML links into text. Each link dict has 'keyword' and 'url'.

    Only replaces the first occurrence of each keyword.
    """
    for link in links:
        keyword = link["keyword"]
        url = link["url"]
        escaped_keyword = escape_html(keyword)
        html_link = f'<a href="{url}">{escaped_keyword}</a>'
        text = text.replace(keyword, html_link, 1)
    return text


def format_post_preview(
    post_id: int,
    topic: str,
    text: str,
    fact_score: float | None = None,
    state: str = "",
) -> str:
    """Format a post preview for Telegram admin notification."""
    lines = [
        f"<b>Post #{post_id}</b>",
        f"<b>Тема:</b> {escape_html(topic)}",
        f"<b>Статус:</b> {escape_html(state)}",
    ]
    if fact_score is not None:
        lines.append(f"<b>Факт-чек:</b> {fact_score:.0%}")
    lines.append("")
    lines.append(text)
    return "\n".join(lines)


def extract_domain(url: str) -> str:
    """Extract domain from URL."""
    match = re.match(r"https?://(?:www\.)?([^/]+)", url)
    return match.group(1) if match else url
