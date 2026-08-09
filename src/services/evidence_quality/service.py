"""Orchestration and persistence for modular evidence-quality passes."""

import hashlib
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
from src.services.evidence_quality.article_cleaner import (
    CLEANER_PROMPT_VERSION,
    MIN_EXACT_SENTENCE_RATE,
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
        normalized = self.normalizer.normalize(article.content)
        repair_flags = {
            ArticleQualityFlag.EMPTY,
            ArticleQualityFlag.TOO_SHORT,
            ArticleQualityFlag.CONSENT_LEADING,
            ArticleQualityFlag.TRUNCATED,
            ArticleQualityFlag.TOO_LONG,
            ArticleQualityFlag.LINK_HEAVY,
            ArticleQualityFlag.RAW_HTML,
            ArticleQualityFlag.EXACT_DUPLICATE,
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
            id=hashlib.sha256(record_key).hexdigest(),
            article_id=article.id,
            dataset_version=self.dataset_version,
            original_content_hash=normalized.original_content_hash,
            normalized_content_hash=normalized.normalized_content_hash,
            normalized_content=normalized.normalized_content,
            flags=normalized.flags,
            status=status,
            normalizer_version=NORMALIZER_VERSION,
            metadata=normalized.metadata,
        )
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

    async def clean_article(
        self,
        article: Article,
        record: Optional[ArticleQualityRecord] = None,
    ) -> ArticleQualityRecord:
        """Create readable Markdown while retaining the normalized snapshot."""
        if self.cleaner is None:
            raise RuntimeError("No article cleaner configured")
        record = record or self.get_article_record(article.id)
        record = record or self.process_article(article)
        record.clean_markdown = await self.cleaner.clean(record.normalized_content)
        record.cleaner_model = self.cleaner.llm.model_name
        record.cleaner_prompt_version = CLEANER_PROMPT_VERSION
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
        fidelity_failed = (
            fidelity["sentence_count"] > 0
            and fidelity["exact_visible_sentence_rate"] < MIN_EXACT_SENTENCE_RATE
        )
        record.status = (
            QualityStatus.NEEDS_REPAIR
            if fidelity_failed
            or any(flag in blocking_flags for flag in record.flags)
            else QualityStatus.COMPLETE
        )
        record.updated_at = datetime.now(timezone.utc)
        self.db.save(ArticleQualityRecord, record)
        return record

    async def validate_event(
        self,
        event: Event,
        article: Article,
        article_record: Optional[ArticleQualityRecord] = None,
    ) -> Tuple[EventEvidenceExtraction, EventEvidenceVerification]:
        """Run exact evidence extraction followed by independent verification."""
        if self.extractor is None or self.verifier is None:
            raise RuntimeError("Both event extractor and verifier must be configured")
        article_record = article_record or self.get_article_record(article.id)
        article_record = article_record or self.process_article(article)
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
