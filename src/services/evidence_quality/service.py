"""Orchestration and persistence for modular evidence-quality passes."""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Tuple

from src.core.database import GenericDatabase
from src.domain.models import (
    Article,
    ArticleQualityFlag,
    ArticleQualityRecord,
    DatasetRepairRecord,
    Event,
    EventEvidenceExtraction,
    EventEvidenceVerification,
    QualityStatus,
)


@dataclass(frozen=True)
class QuestionEvidenceReadiness:
    """Cleanup-barrier state for the articles linked to one question."""

    question_id: str
    dataset_version: str
    total_articles: int
    quality_managed_articles: int
    cleaned_articles: int
    pending_cleanup_articles: int
    blocked_articles: int
    missing_quality_records: int

    @property
    def is_quality_managed(self) -> bool:
        """Return whether this question has entered the quality pipeline."""
        return self.quality_managed_articles > 0

    @property
    def is_ready(self) -> bool:
        """Return whether downstream reasoning may use the cleaned evidence."""
        return (
            self.is_quality_managed
            and self.total_articles > 0
            and self.cleaned_articles > 0
            and self.pending_cleanup_articles == 0
            and self.missing_quality_records == 0
        )

    def blocking_reason(self) -> str:
        """Describe why the question has not crossed the cleanup barrier."""
        if not self.is_quality_managed:
            return "question has no versioned article-quality records"
        problems = []
        if self.missing_quality_records:
            problems.append(
                f"{self.missing_quality_records} article(s) lack quality records"
            )
        if self.pending_cleanup_articles:
            problems.append(
                f"{self.pending_cleanup_articles} eligible article(s) await cleanup"
            )
        if not self.cleaned_articles:
            problems.append("no valid cleaned articles remain")
        return "; ".join(problems) or "evidence cleanup is incomplete"
from src.services.evidence_quality.article_cleaner import (
    CLEANER_PROMPT_VERSION,
    MIN_EXACT_SENTENCE_RATE,
    ArticleValidity,
    ArticleMarkdownCleaner,
    measure_cleaning_fidelity,
)
from src.services.evidence_quality.article_normalizer import (
    NORMALIZER_VERSION,
    ArticleNormalizer,
)
from src.services.evidence_quality.event_grounding import (
    EventEvidenceExtractor,
    EventEvidenceVerifier,
)


class EvidenceQualityService:
    """Run quality passes without mutating original article or event rows."""

    def __init__(
        self,
        db: GenericDatabase,
        dataset_version: str,
        normalizer: Optional[ArticleNormalizer] = None,
        cleaner: Optional[ArticleMarkdownCleaner] = None,
        extractor: Optional[EventEvidenceExtractor] = None,
        verifier: Optional[EventEvidenceVerifier] = None,
    ) -> None:
        self.db = db
        self.dataset_version = dataset_version
        self.normalizer = normalizer or ArticleNormalizer()
        self.cleaner = cleaner
        self.extractor = extractor
        self.verifier = verifier
        for model in (
            ArticleQualityRecord,
            EventEvidenceExtraction,
            EventEvidenceVerification,
            DatasetRepairRecord,
        ):
            self.db.create_table(model)
        self.db.ensure_column(
            EventEvidenceExtraction,
            "traceability_version",
            "TEXT",
        )

    def process_article(self, article: Article) -> ArticleQualityRecord:
        """Run the deterministic pass and persist its derived representation."""
        normalized = self.normalizer.normalize(
            article.content,
            expected_title=article.title,
        )
        current = self.get_article_record(article.id)
        repair_flags = {
            ArticleQualityFlag.EMPTY,
            ArticleQualityFlag.TOO_SHORT,
            ArticleQualityFlag.CONSENT_LEADING,
            ArticleQualityFlag.TRUNCATED,
            ArticleQualityFlag.TOO_LONG,
            ArticleQualityFlag.LINK_HEAVY,
            ArticleQualityFlag.RAW_HTML,
            ArticleQualityFlag.EXACT_DUPLICATE,
            ArticleQualityFlag.ERROR_PAGE,
            ArticleQualityFlag.ACCESS_BLOCK,
            ArticleQualityFlag.LIKELY_WRONG_PAGE,
        }
        existing = self.db.get_many(
            ArticleQualityRecord,
            filters={
                "dataset_version": self.dataset_version,
                "normalized_content_hash": normalized.normalized_content_hash,
            },
        )
        duplicate_candidates = sorted(
            {record.article_id for record in existing} | {article.id}
        )
        duplicate_of = duplicate_candidates[0]
        if article.id != duplicate_of:
            normalized.flags.append(ArticleQualityFlag.EXACT_DUPLICATE)
            normalized.metadata["duplicate_of_article_id"] = duplicate_of
        status = (
            QualityStatus.NEEDS_REPAIR
            if any(flag in repair_flags for flag in normalized.flags)
            else QualityStatus.COMPLETE
        )
        record_key = (
            f"{self.dataset_version}:{article.id}:{NORMALIZER_VERSION}"
        ).encode("utf-8")
        record = ArticleQualityRecord(
            id=current.id if current else hashlib.sha256(record_key).hexdigest(),
            article_id=article.id,
            dataset_version=self.dataset_version,
            original_content_hash=normalized.original_content_hash,
            normalized_content_hash=normalized.normalized_content_hash,
            normalized_content=normalized.normalized_content,
            flags=normalized.flags,
            status=status,
            normalizer_version=NORMALIZER_VERSION,
            clean_markdown=current.clean_markdown if current else None,
            cleaner_model=current.cleaner_model if current else None,
            cleaner_prompt_version=(
                current.cleaner_prompt_version if current else None
            ),
            metadata={
                **(current.metadata if current else {}),
                **normalized.metadata,
            },
            created_at=current.created_at if current else datetime.now(timezone.utc),
            updated_at=current.updated_at if current else None,
        )
        identity_blocking_flags = {
            ArticleQualityFlag.EMPTY,
            ArticleQualityFlag.TOO_SHORT,
            ArticleQualityFlag.TRUNCATED,
            ArticleQualityFlag.ERROR_PAGE,
            ArticleQualityFlag.ACCESS_BLOCK,
            ArticleQualityFlag.LIKELY_WRONG_PAGE,
        }
        if (
            current
            and current.clean_markdown
            and not any(flag in identity_blocking_flags for flag in record.flags)
        ):
            record.status = current.status
        self.db.save(ArticleQualityRecord, record)
        return record

    def get_article_record(self, article_id: str) -> Optional[ArticleQualityRecord]:
        """Return the current deterministic record for an article and release."""
        records = self.db.get_many(
            ArticleQualityRecord,
            filters={
                "article_id": article_id,
                "dataset_version": self.dataset_version,
            },
        )
        return records[0] if records else None

    def ensure_article_record(self, article: Article) -> ArticleQualityRecord:
        """Return an article record produced by the current normalizer."""
        record = self.get_article_record(article.id)
        if record is None or record.normalizer_version != NORMALIZER_VERSION:
            return self.process_article(article)
        return record

    def question_readiness(self, question_id: str) -> QuestionEvidenceReadiness:
        """Summarize whether a question can proceed to cleaned-evidence reasoning."""
        articles = []
        for article in self.db.get_many(Article):
            related_ids = article.metadata.get("related_question_ids", [])
            if (
                article.collected_for_question_id == question_id
                or question_id in related_ids
            ):
                articles.append(article)

        records = {
            record.article_id: record
            for record in self.db.get_many(
                ArticleQualityRecord,
                filters={"dataset_version": self.dataset_version},
            )
            if record.article_id in {article.id for article in articles}
        }
        cleaned = 0
        pending = 0
        blocked = 0
        missing = 0
        for article in articles:
            record = records.get(article.id)
            if record is None:
                missing += 1
                continue
            if not self.article_is_eligible_for_cleanup(record):
                blocked += 1
            elif (
                record.cleaner_model
                and record.clean_markdown
                and record.status == QualityStatus.COMPLETE
            ):
                cleaned += 1
            elif record.cleaner_model:
                blocked += 1
            else:
                pending += 1

        return QuestionEvidenceReadiness(
            question_id=question_id,
            dataset_version=self.dataset_version,
            total_articles=len(articles),
            quality_managed_articles=len(records),
            cleaned_articles=cleaned,
            pending_cleanup_articles=pending,
            blocked_articles=blocked,
            missing_quality_records=missing,
        )

    async def clean_article(
        self,
        article: Article,
        record: Optional[ArticleQualityRecord] = None,
    ) -> ArticleQualityRecord:
        """Create readable Markdown while retaining the normalized snapshot."""
        if self.cleaner is None:
            raise RuntimeError("No article cleaner configured")
        record = record or self.ensure_article_record(article)
        if not self.article_is_eligible_for_cleanup(record):
            identity = record.metadata.get("identity_check", {})
            reasons = identity.get("reasons") or [
                flag.value for flag in record.flags
            ]
            raise ValueError(
                f"Article {article.id} is ineligible for LLM cleanup: "
                f"{', '.join(reasons)}"
            )
        cleanup = await self.cleaner.clean(
            record.normalized_content,
            expected_title=article.title,
        )
        record.clean_markdown = cleanup.clean_markdown
        record.cleaner_model = self.cleaner.llm.model_name
        record.cleaner_prompt_version = CLEANER_PROMPT_VERSION
        record.metadata["cleaner_validity"] = {
            "article_validity": cleanup.article_validity.value,
            "validity_reasons": cleanup.validity_reasons,
            "chunk_assessments": [
                {
                    "article_validity": item.article_validity.value,
                    "validity_reason": item.validity_reason,
                }
                for item in cleanup.chunk_assessments
            ],
        }
        fidelity = measure_cleaning_fidelity(
            record.normalized_content,
            record.clean_markdown,
        )
        record.metadata["cleaner_fidelity"] = fidelity
        blocking_flags = {
            ArticleQualityFlag.EMPTY,
            ArticleQualityFlag.TOO_SHORT,
            ArticleQualityFlag.TRUNCATED,
            ArticleQualityFlag.EXACT_DUPLICATE,
        }
        fidelity_failed = fidelity["sentence_count"] == 0 or (
            fidelity["exact_visible_sentence_rate"] < MIN_EXACT_SENTENCE_RATE
        )
        record.status = (
            QualityStatus.NEEDS_REPAIR
            if cleanup.article_validity != ArticleValidity.VALID
            or fidelity_failed
            or any(flag in blocking_flags for flag in record.flags)
            else QualityStatus.COMPLETE
        )
        record.updated_at = datetime.now(timezone.utc)
        self.db.save(ArticleQualityRecord, record)
        return record

    def record_terminal_cleanup_failure(
        self,
        article: Article,
        error: Exception,
    ) -> ArticleQualityRecord:
        """Persist a bounded model failure without claiming cleaned content."""
        if self.cleaner is None:
            raise RuntimeError("No article cleaner configured")
        record = self.ensure_article_record(article)
        record.cleaner_model = self.cleaner.llm.model_name
        record.cleaner_prompt_version = CLEANER_PROMPT_VERSION
        record.status = QualityStatus.NEEDS_REPAIR
        record.metadata["cleaner_failure"] = {
            "error_type": type(error).__name__,
            "error": str(error),
            "terminal": True,
        }
        record.updated_at = datetime.now(timezone.utc)
        self.db.save(ArticleQualityRecord, record)
        return record

    @staticmethod
    def article_is_eligible_for_cleanup(record: ArticleQualityRecord) -> bool:
        """Return whether a snapshot may be sent to the cleanup model."""
        return (
            EvidenceQualityService.article_is_eligible_for_llm(record)
            and ArticleQualityFlag.EXACT_DUPLICATE not in record.flags
        )

    @staticmethod
    def article_is_eligible_for_llm(record: ArticleQualityRecord) -> bool:
        """Return whether a snapshot may be sent to any validation model."""
        blocking_flags = {
            ArticleQualityFlag.EMPTY,
            ArticleQualityFlag.TOO_SHORT,
            ArticleQualityFlag.TRUNCATED,
            ArticleQualityFlag.ERROR_PAGE,
            ArticleQualityFlag.ACCESS_BLOCK,
            ArticleQualityFlag.LIKELY_WRONG_PAGE,
        }
        deterministic_block = any(flag in blocking_flags for flag in record.flags)
        failed_cleanup = bool(
            record.cleaner_model and record.status != QualityStatus.COMPLETE
        )
        return not deterministic_block and not failed_cleanup

    async def validate_event(
        self,
        event: Event,
        article: Article,
        article_record: Optional[ArticleQualityRecord] = None,
    ) -> Tuple[EventEvidenceExtraction, EventEvidenceVerification]:
        """Run exact evidence extraction followed by independent verification."""
        if self.extractor is None or self.verifier is None:
            raise RuntimeError("Both event extractor and verifier must be configured")
        article_record = article_record or self.ensure_article_record(article)
        if not self.article_is_eligible_for_llm(article_record):
            identity = article_record.metadata.get("identity_check", {})
            reasons = identity.get("reasons") or [
                flag.value for flag in article_record.flags
            ]
            raise ValueError(
                f"Article {article.id} is ineligible for event validation: "
                f"{', '.join(reasons)}"
            )
        input_content = (
            article_record.clean_markdown or article_record.normalized_content
        )
        if not article_record.clean_markdown and len(input_content) > 50_000:
            raise ValueError(
                f"Article {article.id} exceeds 50,000 characters; run the "
                "Markdown cleanup pass before event grounding"
            )
        extraction = await self.extractor.extract(
            event=event,
            article=article,
            input_content=input_content,
            traceability_snapshot=article_record.normalized_content,
            dataset_version=self.dataset_version,
        )
        self.db.save(EventEvidenceExtraction, extraction)
        verification = await self.verifier.verify(event, article, extraction)
        self.db.save(EventEvidenceVerification, verification)
        self._record_repair_proposal(event, article, extraction, verification)
        return extraction, verification

    def _record_repair_proposal(
        self,
        event: Event,
        article: Article,
        extraction: EventEvidenceExtraction,
        verification: EventEvidenceVerification,
    ) -> DatasetRepairRecord:
        after = {}
        if extraction.proposed_claim:
            after["description"] = extraction.proposed_claim
        if extraction.proposed_date:
            after["occurred_date"] = extraction.proposed_date
        record = DatasetRepairRecord(
            dataset_version=self.dataset_version,
            event_id=event.id,
            action=verification.action,
            extraction_id=extraction.id,
            verification_id=verification.id,
            before={
                "description": event.description,
                "occurred_date": event.occurred_date.isoformat()
                if event.occurred_date
                else None,
                "source_article_id": article.id,
            },
            after=after,
            applied=False,
        )
        self.db.save(DatasetRepairRecord, record)
        return record
