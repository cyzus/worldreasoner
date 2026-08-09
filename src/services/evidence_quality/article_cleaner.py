"""LLM readability pass for normalized article snapshots."""

import re
from typing import Any, Dict, List

from src.services.evidence_quality.article_normalizer import (
    normalize_for_traceability,
)
from src.services.evidence_quality.llm_client import StructuredLLM


CLEANER_PROMPT_VERSION = "article-cleaner-v1"
MIN_EXACT_SENTENCE_RATE = 0.7
MIN_FIDELITY_SENTENCE_CHARS = 40


def measure_cleaning_fidelity(source: str, cleaned: str) -> Dict[str, Any]:
    """Measure whether sentence-length cleaned text remains visible in source."""
    source_visible = normalize_for_traceability(source)
    cleaned_body = re.sub(r"(?m)^\s{0,3}#{1,6}\s+.*$", "", cleaned)
    cleaned_visible = normalize_for_traceability(cleaned_body)
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", cleaned_visible)
        if len(sentence.strip()) >= MIN_FIDELITY_SENTENCE_CHARS
    ]
    traceable = [sentence for sentence in sentences if sentence in source_visible]
    exact_rate = len(traceable) / len(sentences) if sentences else None
    return {
        "source_chars": len(source),
        "clean_chars": len(cleaned),
        "retained_ratio": len(cleaned) / len(source) if source else None,
        "sentence_count": len(sentences),
        "traceable_sentence_count": len(traceable),
        "exact_visible_sentence_rate": exact_rate,
        "minimum_expected_rate": MIN_EXACT_SENTENCE_RATE,
        "minimum_sentence_chars": MIN_FIDELITY_SENTENCE_CHARS,
    }


class ArticleMarkdownCleaner:
    """Remove page furniture while preserving the article's factual content."""

    def __init__(self, llm: StructuredLLM, chunk_chars: int = 24_000) -> None:
        self.llm = llm
        self.chunk_chars = chunk_chars

    async def clean(self, content: str) -> str:
        """Clean an article in bounded paragraph-aligned chunks."""
        chunks = self._split_chunks(content)
        cleaned: List[str] = []
        for index, chunk in enumerate(chunks, 1):
            result = await self.llm.complete_json(
                system_prompt=self._system_prompt(),
                user_prompt=(
                    f"Document chunk {index} of {len(chunks)}:\n\n{chunk}\n\n"
                    'Return JSON with one string field: "clean_markdown".'
                ),
            )
            text = result.get("clean_markdown")
            if not isinstance(text, str):
                raise ValueError("Cleaner response omitted clean_markdown")
            cleaned.append(text.strip())
        return "\n\n".join(part for part in cleaned if part).strip()

    def _split_chunks(self, content: str) -> List[str]:
        if len(content) <= self.chunk_chars:
            return [content]

        paragraphs = content.split("\n\n")
        chunks: List[str] = []
        current: List[str] = []
        current_size = 0
        for paragraph in paragraphs:
            if current and current_size + len(paragraph) + 2 > self.chunk_chars:
                chunks.append("\n\n".join(current))
                current = []
                current_size = 0
            if len(paragraph) > self.chunk_chars:
                if current:
                    chunks.append("\n\n".join(current))
                    current = []
                    current_size = 0
                chunks.extend(
                    paragraph[start : start + self.chunk_chars]
                    for start in range(0, len(paragraph), self.chunk_chars)
                )
                continue
            current.append(paragraph)
            current_size += len(paragraph) + 2
        if current:
            chunks.append("\n\n".join(current))
        return chunks

    @staticmethod
    def _system_prompt() -> str:
        return """You clean archived web pages for human annotation.
Remove navigation, cookie notices, advertisements, recommendations, repeated
boilerplate, and unrelated page furniture. Preserve all substantive claims,
names, dates, numbers, quotations, uncertainty, and negation. Use only text in
the supplied snapshot. Do not summarize, infer missing content, correct facts,
or add outside knowledge. Return readable Markdown in valid JSON only."""
