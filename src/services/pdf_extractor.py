"""PDF text extraction service using pdfplumber."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import httpx
import pdfplumber

from src.utils.text import clean_text

logger = logging.getLogger(__name__)


class PdfExtractorService:
    """Extract text from PDF files (local or remote URLs)."""

    def __init__(self, timeout: int = 60):
        self.timeout = timeout

    async def extract_from_url(self, url: str, max_pages: int = 50) -> str:
        """Download a PDF from URL and extract text."""
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(response.content)
            tmp.flush()
            return self.extract_from_file(tmp.name, max_pages)

    def extract_from_file(self, file_path: str, max_pages: int = 50) -> str:
        """Extract text from a local PDF file."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {file_path}")

        pages_text = []
        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages[:max_pages]):
                text = page.extract_text()
                if text:
                    pages_text.append(text)

        full_text = "\n\n".join(pages_text)
        full_text = clean_text(full_text)
        logger.info("Extracted PDF %s: %d pages, %d chars", file_path, len(pages_text), len(full_text))
        return full_text
