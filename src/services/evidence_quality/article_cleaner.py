"""LLM readability pass for normalized article snapshots."""

import re
from enum import Enum
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from src.services.evidence_quality.article_normalizer import (
    normalize_for_traceability,
)
from src.services.evidence_quality.llm_client import StructuredLLM


CLEANER_PROMPT_VERSION = "article-cleaner-v2"
MIN_EXACT_SENTENCE_RATE = 0.7
MIN_FIDELITY_SENTENCE_CHARS = 40


class ArticleValidity(str, Enum):
    """Whether a snapshot chunk contains substantive target-article text."""

    VALID = "valid"
    INVALID = "invalid"
    UNCERTAIN = "uncertain"


class CleanMarkdownResponse(BaseModel):
    """Schema-constrained response for one cleaned article chunk."""

    article_validity: ArticleValidity
    validity_reason: str
    clean_markdown: str


class ArticleCleanupResult(BaseModel):
    """Aggregated validity and Markdown from every bounded document chunk."""

    article_validity: ArticleValidity
    validity_reasons: List[str] = Field(default_factory=list)
    clean_markdown: str
    chunk_assessments: List[CleanMarkdownResponse] = Field(default_factory=list)


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

    async def clean(
        self,
        content: str,
        expected_title: str = "",
    ) -> ArticleCleanupResult:
        """Assess and clean an article in bounded paragraph-aligned chunks."""
        chunks = self._split_chunks(content)
        cleaned: List[str] = []
        assessments: List[CleanMarkdownResponse] = []
        for index, chunk in enumerate(chunks, 1):
            result = await self.llm.complete_json(
                system_prompt=self._system_prompt(),
                user_prompt=(
                    f"Expected article title: {expected_title or '[unknown]'}\n"
                    f"Document chunk {index} of {len(chunks)}:\n\n{chunk}\n\n"
                    "Return article_validity, validity_reason, and "
                    "clean_markdown in one JSON object."
                ),
                response_model=CleanMarkdownResponse,
            )
            assessment = CleanMarkdownResponse.model_validate(result)
            if (
                assessment.article_validity == ArticleValidity.VALID
                and not assessment.clean_markdown.strip()
            ):
                assessment = assessment.model_copy(
                    update={
                        "article_validity": ArticleValidity.UNCERTAIN,
                        "validity_reason": (
                            "Model marked the chunk valid but returned no article text."
                        ),
                    }
                )
            assessments.append(assessment)
            if assessment.article_validity == ArticleValidity.VALID:
                cleaned.append(assessment.clean_markdown.strip())

        validities = {item.article_validity for item in assessments}
        if ArticleValidity.VALID in validities:
            article_validity = ArticleValidity.VALID
        elif ArticleValidity.UNCERTAIN in validities:
            article_validity = ArticleValidity.UNCERTAIN
        else:
            article_validity = ArticleValidity.INVALID
        reasons = list(
            dict.fromkeys(
                item.validity_reason.strip()
                for item in assessments
                if item.validity_reason.strip()
            )
        )
        return ArticleCleanupResult(
            article_validity=article_validity,
            validity_reasons=reasons,
            clean_markdown="\n\n".join(part for part in cleaned if part).strip(),
            chunk_assessments=assessments,
        )

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
        return """You validate and clean archived web pages for human annotation.
First decide whether the supplied chunk contains substantive text from the
expected target article. Use "valid" when it contains target-article body text,
"invalid" for consent pages, access challenges, error pages, navigation/listing
pages, unrelated pages, or page furniture without article text, and "uncertain"
when the identity cannot be established. A continuation chunk can be valid even
if it does not repeat the title. For invalid or uncertain chunks, explain why
briefly and return an empty clean_markdown.

Remove navigation, cookie notices, advertisements, recommendations, repeated
boilerplate, and unrelated page furniture. Preserve all substantive claims,
names, dates, numbers, quotations, uncertainty, and negation. Use only text in
the supplied snapshot. Do not summarize, infer missing content, correct facts,
or add outside knowledge. Return readable Markdown in valid JSON only."""
