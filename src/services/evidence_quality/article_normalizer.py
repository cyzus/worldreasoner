"""Deterministic normalization and diagnostics for article snapshots."""

import hashlib
import html
import json
import re
from typing import Any, Dict, List, Tuple

from pydantic import BaseModel, Field

from src.domain.models import ArticleQualityFlag


NORMALIZER_VERSION = "article-normalizer-v1"
_LINK_PATTERN = re.compile(r"\[[^\]]*\]\([^)]*\)")
_HTML_PATTERN = re.compile(r"<(?:html|body|div|p|script|style|article)\b", re.I)
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MARKDOWN_HEADING_PATTERN = re.compile(r"(?m)^\s{0,3}#{1,6}\s+")
_MARKDOWN_LIST_PATTERN = re.compile(r"(?m)^\s*[-+*]\s+")
_CONSENT_PATTERN = re.compile(
    r"^.{0,800}\b(?:cookie(?:s)?|privacy choices|consent|accept all|"
    r"your privacy)\b",
    re.I | re.S,
)
_TRUNCATION_MARKERS = (
    "content truncated",
    "[truncated]",
    "... truncated",
    "maximum content length",
)


class NormalizedArticle(BaseModel):
    """Result of the deterministic article normalization pass."""

    original_content_hash: str
    normalized_content_hash: str
    normalized_content: str
    flags: List[ArticleQualityFlag] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ArticleNormalizer:
    """Normalize storage artifacts without rewriting substantive article text."""

    def __init__(
        self,
        min_chars: int = 100,
        max_chars: int = 100_000,
        max_markdown_links: int = 100,
    ) -> None:
        self.min_chars = min_chars
        self.max_chars = max_chars
        self.max_markdown_links = max_markdown_links

    def normalize(self, content: str) -> NormalizedArticle:
        """Unwrap known containers, normalize encoding, and flag quality risks."""
        original = content or ""
        normalized, wrapper_metadata, unwrapped = self._unwrap_json(original)
        normalized = self._normalize_text(normalized)

        flags: List[ArticleQualityFlag] = []
        if unwrapped:
            flags.append(ArticleQualityFlag.JSON_WRAPPER)
        if not normalized:
            flags.append(ArticleQualityFlag.EMPTY)
        elif len(normalized) < self.min_chars:
            flags.append(ArticleQualityFlag.TOO_SHORT)
        if len(normalized) > self.max_chars:
            flags.append(ArticleQualityFlag.TOO_LONG)
        if len(_LINK_PATTERN.findall(normalized)) > self.max_markdown_links:
            flags.append(ArticleQualityFlag.LINK_HEAVY)
        if _CONSENT_PATTERN.search(normalized):
            flags.append(ArticleQualityFlag.CONSENT_LEADING)
        if _HTML_PATTERN.search(normalized):
            flags.append(ArticleQualityFlag.RAW_HTML)
        if any(marker in normalized.lower() for marker in _TRUNCATION_MARKERS):
            flags.append(ArticleQualityFlag.TRUNCATED)

        return NormalizedArticle(
            original_content_hash=self.content_hash(original),
            normalized_content_hash=self.content_hash(normalized),
            normalized_content=normalized,
            flags=flags,
            metadata={"wrapper_metadata": wrapper_metadata},
        )

    @staticmethod
    def content_hash(content: str) -> str:
        """Hash content after only line-ending normalization."""
        canonical = (content or "").replace("\r\n", "\n").replace("\r", "\n")
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_text(content: str) -> str:
        content = content.replace("\x00", "")
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        content = "\n".join(line.rstrip() for line in content.splitlines())
        content = re.sub(r"\n{4,}", "\n\n\n", content)
        return content.strip()

    @staticmethod
    def _unwrap_json(content: str) -> Tuple[str, Dict[str, Any], bool]:
        stripped = content.strip()
        if not stripped.startswith("{"):
            return content, {}, False
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            return content, {}, False
        if not isinstance(payload, dict):
            return content, {}, False

        markdown = payload.get("markdown")
        if isinstance(markdown, dict):
            markdown = markdown.get("fit_markdown") or markdown.get("raw_markdown")
        if not isinstance(markdown, str):
            return content, {}, False

        metadata = {
            key: value
            for key, value in payload.items()
            if key != "markdown"
            and isinstance(value, (str, int, float, bool, type(None)))
        }
        return markdown, metadata, True


def normalize_for_traceability(text: str) -> str:
    """Canonicalize formatting while preserving exact visible article text."""
    visible = html.unescape(text or "")
    visible = _MARKDOWN_IMAGE_PATTERN.sub(r"\1", visible)
    visible = _MARKDOWN_LINK_PATTERN.sub(r"\1", visible)
    visible = _HTML_TAG_PATTERN.sub(" ", visible)
    visible = _MARKDOWN_HEADING_PATTERN.sub("", visible)
    visible = _MARKDOWN_LIST_PATTERN.sub("", visible)
    visible = visible.replace("**", "").replace("__", "")
    visible = visible.replace("~~", "").replace("`", "")
    return " ".join(visible.split())


def passage_is_traceable(passage: str, snapshot: str) -> bool:
    """Return whether a passage occurs in the preserved snapshot."""
    candidate = normalize_for_traceability(passage)
    return bool(candidate) and candidate in normalize_for_traceability(snapshot)
