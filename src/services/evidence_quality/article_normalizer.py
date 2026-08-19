"""Deterministic normalization and diagnostics for article snapshots."""

import hashlib
import html
import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, Field

from src.domain.models import ArticleQualityFlag


NORMALIZER_VERSION = "article-normalizer-v5"
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
_ERROR_PAGE_PATTERN = re.compile(
    r"\b404\s+(?:page\s+)?not\s+found\b|"
    r"\bpage unavailable\b|"
    r"\bthe page you (?:are looking for|requested) "
    r"(?:could not be found|does not exist)\b|"
    r"\bwhoops!?\s+something went wrong\b",
    re.I,
)
_ACCESS_BLOCK_PATTERN = re.compile(
    r"\bwe(?:'|’)ve detected unusual activity from your (?:computer )?network\b|"
    r"\bplease (?:enable|make sure your browser supports) javascript "
    r"(?:and cookies )?to continue\b|"
    r"\bverify (?:that )?you are (?:a )?human\b|"
    r"\bplease click the box below to let us know you(?:'|’)re not a robot\b|"
    r"\baccess denied\b.{0,160}\byou do not have permission\b|"
    r"\ba required part of this site couldn(?:'|’)t load\b|"
    r"\bincorrect captcha\b",
    re.I | re.S,
)
_MSN_CONSENT_SHELL_PATTERN = re.compile(
    r"^.{0,200}?## More for You\s*\n"
    r"## More for You\s*\n"
    r"## Microsoft Cares About Your Privacy\b",
    re.I | re.S,
)
_MSN_PRIVACY_MARKER_PATTERN = re.compile(
    r"\bMicrosoft Cares About Your Privacy\b.{0,3000}"
    r"\b(?:Number of Partners|List of Partners|Manage Preferences)\b",
    re.I | re.S,
)
_COOKIE_SETTINGS_SHELL_MARKERS = (
    "this website uses cookies",
    "consent selection",
    "[#gpc_banner_icon#]",
    "[#gpc_toast_text#]",
)
_CNBC_FOOTER_PATTERN = re.compile(
    r"Data is a real-time snapshot \*Data is delayed at least 15 minutes\. "
    r"Global Business and Financial News, Stock Quotes, and Market Data "
    r"and Analysis\.",
    re.I,
)
_TITLE_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "was",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "will",
    "with",
}
MIN_TITLE_TOKENS_FOR_IDENTITY = 4
MIN_TITLE_TOKEN_COVERAGE = 0.3
MIN_LISTING_LINKS = 10


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

    def normalize(
        self,
        content: str,
        expected_title: Optional[str] = None,
    ) -> NormalizedArticle:
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

        identity = assess_snapshot_identity(expected_title, normalized)
        if identity["error_page_detected"]:
            flags.append(ArticleQualityFlag.ERROR_PAGE)
        if identity["access_block_detected"]:
            flags.append(ArticleQualityFlag.ACCESS_BLOCK)
        if identity["likely_wrong_page"]:
            flags.append(ArticleQualityFlag.LIKELY_WRONG_PAGE)

        return NormalizedArticle(
            original_content_hash=self.content_hash(original),
            normalized_content_hash=self.content_hash(normalized),
            normalized_content=normalized,
            flags=flags,
            metadata={
                "wrapper_metadata": wrapper_metadata,
                "identity_check": identity,
            },
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


def assess_snapshot_identity(
    expected_title: Optional[str],
    content: str,
) -> Dict[str, Any]:
    """Apply conservative deterministic checks for wrong or unavailable pages."""
    title_tokens = _identity_tokens(expected_title or "")
    content_tokens = _identity_tokens(content)
    visible_content_tokens = _identity_tokens(normalize_for_traceability(content))
    coverage = (
        len(title_tokens & content_tokens) / len(title_tokens)
        if title_tokens
        else None
    )
    visible_coverage = (
        len(title_tokens & visible_content_tokens) / len(title_tokens)
        if title_tokens
        else None
    )
    link_count = len(_LINK_PATTERN.findall(content))
    leading_content = content[:3_000]
    error_page_detected = bool(_ERROR_PAGE_PATTERN.search(content))
    access_block_detected = bool(_ACCESS_BLOCK_PATTERN.search(leading_content))
    low_coverage_listing = bool(
        len(title_tokens) >= MIN_TITLE_TOKENS_FOR_IDENTITY
        and coverage is not None
        and coverage < MIN_TITLE_TOKEN_COVERAGE
        and link_count >= MIN_LISTING_LINKS
    )
    consent_shell_detected = bool(
        _MSN_CONSENT_SHELL_PATTERN.search(content)
        or (
            _MSN_PRIVACY_MARKER_PATTERN.search(content)
            and visible_coverage is not None
            and visible_coverage < MIN_TITLE_TOKEN_COVERAGE
        )
    )
    lowered_content = content.lower()
    cookie_settings_shell_detected = bool(
        all(marker in lowered_content for marker in _COOKIE_SETTINGS_SHELL_MARKERS)
    )
    navigation_shell_detected = bool(
        _CNBC_FOOTER_PATTERN.search(content)
        and link_count >= 100
        and not _MARKDOWN_HEADING_PATTERN.search(content)
    )
    likely_wrong_page = bool(
        low_coverage_listing
        or consent_shell_detected
        or cookie_settings_shell_detected
        or navigation_shell_detected
    )
    reasons: List[str] = []
    if error_page_detected:
        reasons.append("explicit_error_page_marker")
    if access_block_detected:
        reasons.append("explicit_access_block_marker")
    if low_coverage_listing:
        reasons.append("low_title_coverage_on_link_listing")
    if consent_shell_detected:
        reasons.append("consent_shell_without_article_body")
    if cookie_settings_shell_detected:
        reasons.append("cookie_settings_shell_without_article_body")
    if navigation_shell_detected:
        reasons.append("navigation_shell_without_article_body")
    return {
        "eligible": (
            not error_page_detected
            and not access_block_detected
            and not likely_wrong_page
        ),
        "reasons": reasons,
        "title_token_count": len(title_tokens),
        "title_token_coverage": coverage,
        "visible_title_token_coverage": visible_coverage,
        "markdown_link_count": link_count,
        "error_page_detected": error_page_detected,
        "access_block_detected": access_block_detected,
        "consent_shell_detected": consent_shell_detected,
        "cookie_settings_shell_detected": cookie_settings_shell_detected,
        "navigation_shell_detected": navigation_shell_detected,
        "low_coverage_listing": low_coverage_listing,
        "likely_wrong_page": likely_wrong_page,
        "policy": "snapshot-identity-v4",
    }


def _identity_tokens(text: str) -> Set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2 and token not in _TITLE_STOP_WORDS
    }


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
