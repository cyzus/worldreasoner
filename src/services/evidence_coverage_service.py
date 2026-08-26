"""Question-aware deterministic evidence sufficiency policy."""

from datetime import timedelta
from typing import TYPE_CHECKING, List
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from src.config.pipeline import EvidenceSatisfactionConfig
from src.core.database import GenericDatabase
from src.domain.models import Article, ArticleQualityRecord, Question, QuestionType
from src.services.service_base import ServiceBase

if TYPE_CHECKING:
    from src.pipelines.construction.models import CoverageAssessmentDraft


class EvidenceRequirementProfile(BaseModel):
    """Concrete requirements for one question's hindsight dossier."""

    article_target: int = Field(ge=1)
    min_unique_sources: int = Field(ge=1)
    horizon_days: int = Field(ge=0)
    max_reporting_delay_days: int = Field(ge=0)


class EvidenceCoverageService(ServiceBase):
    """Combine deterministic dossier statistics with semantic coverage labels."""

    def __init__(
        self,
        db: GenericDatabase,
        config: EvidenceSatisfactionConfig,
    ) -> None:
        super().__init__(db)
        self.config = config

    def profile_for(self, question: Question) -> EvidenceRequirementProfile:
        """Derive a conservative evidence target from horizon and answer type."""
        start = question.estimated_start_time or question.resolution_date
        horizon_days = max(0, (question.resolution_date - start).days)
        if not self.config.adaptive_article_targets:
            target = self.config.min_articles
        elif horizon_days <= 45:
            target = self.config.short_horizon_articles
        elif horizon_days <= 180:
            target = self.config.medium_horizon_articles
        else:
            target = self.config.long_horizon_articles
        if question.question_type in {QuestionType.MCQ, QuestionType.QUANTITY}:
            target += 2
        target = min(target, self.config.min_articles)
        min_sources = min(self.config.min_unique_sources, target)
        return EvidenceRequirementProfile(
            article_target=target,
            min_unique_sources=min_sources,
            horizon_days=horizon_days,
            max_reporting_delay_days=self.config.hindsight_reporting_delay_days,
        )

    def deterministic_gaps(
        self,
        question: Question,
        records: List[ArticleQualityRecord],
    ) -> List[str]:
        """Return count and diversity gaps over approved article versions."""
        profile = self.profile_for(question)
        gaps: List[str] = []
        if len(records) < profile.article_target:
            gaps.append(f"articles ({len(records)} < {profile.article_target})")
        source_keys = {
            self._source_key(article)
            for record in records
            if (article := self.db.get(Article, record.article_id)) is not None
        }
        source_keys.discard("")
        if len(source_keys) < profile.min_unique_sources:
            gaps.append(
                "unique_sources "
                f"({len(source_keys)} < {profile.min_unique_sources})"
            )
        return gaps

    @staticmethod
    def semantic_gaps(assessment: "CoverageAssessmentDraft") -> List[str]:
        """Convert the typed semantic ledger into explicit recovery needs."""
        ledger = assessment.ledger
        gaps = [
            *ledger.critical_gaps,
            *assessment.missing_evidence_needs,
        ]
        requirements = (
            (ledger.outcome_resolution_supported, "outcome resolution support"),
            (ledger.timeline_covered, "timeline coverage"),
            (ledger.key_developments_supported, "key development support"),
            (ledger.citations_traceable, "traceable citations"),
        )
        gaps.extend(label for passed, label in requirements if not passed)
        if not ledger.counterevidence_considered:
            gaps.append("counterevidence or alternative scenario coverage")
        return list(dict.fromkeys(gaps))

    def is_hindsight_eligible(self, question: Question, article: Article) -> bool:
        """Allow bounded post-resolution reporting in reference construction."""
        latest = question.resolution_date + timedelta(
            days=self.config.hindsight_reporting_delay_days
        )
        return article.published_date <= latest

    @staticmethod
    def _source_key(article: Article) -> str:
        if article.url:
            host = urlparse(article.url).netloc.lower()
            if host.startswith("www."):
                host = host[4:]
            if host:
                return host
        return article.source.strip().lower()
