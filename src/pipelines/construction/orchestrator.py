"""Resumable, code-controlled benchmark construction workflow."""

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Protocol, Type
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit
from uuid import uuid4

from pydantic import BaseModel, Field
from smolagents import WebSearchTool as SmolWebSearchTool

from src.config import get_config
from src.config.pipeline import EvidenceSatisfactionConfig
from src.core.database import GenericDatabase
from src.core.llm import LiteLLMClient
from src.domain.models import (
    AliasEntityKind,
    AliasScopeType,
    ApprovedEvidenceDossier,
    Article,
    ArticleQualityRecord,
    ArtifactStatus,
    Domain,
    Event,
    ExplanationArtifact,
    GraphEdgeProposal,
    GraphNodeProposal,
    GraphRevision,
    OutcomeImpactProposal,
    PipelineRun,
    QualityStatus,
    Question,
    QuestionType,
    SearchDossier,
    StageAttempt,
    StageAttemptStatus,
)
from src.pipelines.construction.models import (
    AgentUsage,
    CoverageAssessmentDraft,
    ExplanationDraft,
    GeneratedQuestionDraft,
    GraphDraft,
    SearchQuery,
    SearchPlanDraft,
)
from src.pipelines.construction.prompts import (
    COVERAGE_ASSESSOR_INSTRUCTIONS,
    EXPLANATION_INSTRUCTIONS,
    GRAPH_BUILDER_INSTRUCTIONS,
    GRAPH_REPAIR_INSTRUCTIONS,
    QUESTION_GENERATOR_INSTRUCTIONS,
    SEARCH_PLANNER_INSTRUCTIONS,
)
from src.services.construction_graph_service import ConstructionGraphService
from src.services.evidence_coverage_service import EvidenceCoverageService
from src.services.evidence_quality.article_cleaner import ArticleMarkdownCleaner
from src.services.evidence_quality.llm_client import LiteLLMStructuredClient
from src.services.evidence_quality.service import EvidenceQualityService
from src.services.outcome_event_service import OutcomeEventService
from src.services.pipeline_artifact_service import (
    ArtifactValidationError,
    PipelineArtifactService,
)
from src.services.question_monitor_service import QuestionMonitorService
from src.tools.collectors.article_collector import ArticleCollectorTool
from src.tools.collectors.web_fetch import WebFetchTool
from src.tools.collectors.web_search import WebSearchTool

WORKFLOW_VERSION = "construction-v2"
PROMPT_BUNDLE_VERSION = "construction-prompts-v1"


class StructuredRuntime(Protocol):
    """Runtime boundary used by production SDK calls and deterministic tests."""

    model_id: str

    async def run_structured(
        self,
        name: str,
        instructions: str,
        user_input: str,
        output_type: Type[BaseModel],
        max_turns: int = 4,
    ) -> tuple[BaseModel, AgentUsage]: ...


class ConstructionRunResult(BaseModel):
    """Identifiers proving the materialized output of one complete run."""

    run_id: str
    question_id: str
    evidence_dossier_id: str
    explanation_id: str
    graph_revision_id: str
    article_count: int
    event_count: int
    edge_count: int
    impact_count: int
    token_usage: int
    cost_usd: float


class ConstructionBatchResult(BaseModel):
    """Per-question outcomes for a failure-isolated construction batch."""

    processed: List[ConstructionRunResult] = Field(default_factory=list)
    failed: List[Dict[str, str]] = Field(default_factory=list)
    abstained: List[Dict[str, str]] = Field(default_factory=list)
    skipped: List[Dict[str, str]] = Field(default_factory=list)


class EvidenceAbstentionError(RuntimeError):
    """Raised when bounded collection cannot support benchmark construction."""

    def __init__(self, missing_requirements: List[str], rounds: int) -> None:
        self.missing_requirements = missing_requirements
        self.rounds = rounds
        super().__init__(
            "Evidence requirements not met after "
            f"{rounds} collection rounds: "
            + ", ".join(missing_requirements)
        )


class ConstructionPipeline:
    """Orchestrate bounded specialists around deterministic persistence gates."""

    def __init__(
        self,
        db_path: Path,
        runtime: StructuredRuntime,
        dataset_version: str = "v2-live",
        max_search_results: int = 5,
        max_search_queries_per_round: int = 3,
        requirements: Optional[EvidenceSatisfactionConfig] = None,
        cleaner_concurrency: int = 3,
        max_evidence_rounds: int = 3,
        max_graph_repairs: int = 2,
        max_explanation_repairs: int = 2,
        source_urls: Optional[List[str]] = None,
    ) -> None:
        self.db = GenericDatabase(db_path)
        self.db.initialize_all_tables()
        self.runtime = runtime
        self.dataset_version = dataset_version
        self.max_search_results = max_search_results
        self.max_search_queries_per_round = max_search_queries_per_round
        self.requirements = requirements or EvidenceSatisfactionConfig()
        self.max_evidence_rounds = max_evidence_rounds
        self.max_graph_repairs = max_graph_repairs
        self.max_explanation_repairs = max_explanation_repairs
        self.source_urls = source_urls or []
        self.artifacts = PipelineArtifactService(self.db)
        self._configure_requirements(self.requirements)
        config = get_config()
        cleaner = ArticleMarkdownCleaner(
            LiteLLMStructuredClient(LiteLLMClient(config.llm)),
            request_concurrency=cleaner_concurrency,
        )
        self.quality = EvidenceQualityService(
            self.db,
            dataset_version=dataset_version,
            cleaner=cleaner,
        )

    async def run(self, topic: str) -> ConstructionRunResult:
        """Execute question generation through atomic graph construction."""
        run = self.artifacts.start_run(
            question_id=None,
            dataset_version=self.dataset_version,
            workflow_version=WORKFLOW_VERSION,
            model_configuration={
                "model": self.runtime.model_id,
                "requirements": self.requirements.model_dump(),
                "max_evidence_rounds": self.max_evidence_rounds,
                "max_search_queries_per_round": self.max_search_queries_per_round,
            },
            prompt_bundle_version=PROMPT_BUNDLE_VERSION,
        )
        try:
            question = await self._generate_question(run, topic)
            dossier = await self._collect_evidence(run, question)
            explanation = await self._synthesize_explanation(run, question, dossier)
            revision = await self._build_graph(run, question, dossier, explanation)
            completed = self.artifacts.complete_run(run.id)
            return ConstructionRunResult(
                run_id=run.id,
                question_id=question.id,
                evidence_dossier_id=dossier.id,
                explanation_id=explanation.id,
                graph_revision_id=revision.id,
                article_count=len(dossier.article_version_ids),
                event_count=len(revision.nodes),
                edge_count=len(revision.edges),
                impact_count=len(revision.outcome_impacts),
                token_usage=completed.token_usage,
                cost_usd=completed.cost_usd,
            )
        except Exception as exc:
            active = self.db.get_many(
                PipelineRun, filters={"id": run.id}
            )[0]
            if active.status.value == "running":
                active.status = "failed"
                active.error_summary = str(exc)
                self.db.save(PipelineRun, active)
            raise

    async def run_question(self, question_id: str) -> ConstructionRunResult:
        """Run the backward construction workflow for an existing question."""
        question = self.db.get(Question, question_id)
        if question is None:
            raise RuntimeError(f"Unknown question: {question_id}")
        if question.ground_truth is None:
            raise RuntimeError(f"Question is unresolved: {question_id}")
        if question.resolution_date > datetime.now(timezone.utc):
            raise RuntimeError(f"Question has not reached resolution: {question_id}")
        if question.skip_evidence:
            raise RuntimeError(f"Question is marked to skip evidence: {question_id}")

        outcomes = OutcomeEventService(self.db)
        if not outcomes.get_outcome_events_for_question(question.id):
            outcomes.auto_create_outcome_events(question)
        outcomes.ensure_actual_outcome_alignment(question)

        run = self.artifacts.start_run(
            question_id=question.id,
            dataset_version=self.dataset_version,
            workflow_version=WORKFLOW_VERSION,
            model_configuration={
                "model": self.runtime.model_id,
                "requirements": self.requirements.model_dump(),
                "max_evidence_rounds": self.max_evidence_rounds,
                "entrypoint": "existing_question",
            },
            prompt_bundle_version=PROMPT_BUNDLE_VERSION,
        )
        try:
            dossier = await self._collect_evidence(run, question)
            explanation = await self._synthesize_explanation(
                run, question, dossier
            )
            revision = await self._build_graph(
                run, question, dossier, explanation
            )
            completed = self.artifacts.complete_run(run.id)
            return ConstructionRunResult(
                run_id=run.id,
                question_id=question.id,
                evidence_dossier_id=dossier.id,
                explanation_id=explanation.id,
                graph_revision_id=revision.id,
                article_count=len(dossier.article_version_ids),
                event_count=len(revision.nodes),
                edge_count=len(revision.edges),
                impact_count=len(revision.outcome_impacts),
                token_usage=completed.token_usage,
                cost_usd=completed.cost_usd,
            )
        except Exception as exc:
            active = self.db.get(PipelineRun, run.id)
            if active is not None and active.status.value == "running":
                active.status = "failed"
                active.error_summary = str(exc)
                self.db.save(PipelineRun, active)
            raise

    async def run_questions(
        self,
        question_ids: List[str],
    ) -> ConstructionBatchResult:
        """Process existing questions sequentially without aborting the batch."""
        result = ConstructionBatchResult()
        for question_id in question_ids:
            question = self.db.get(Question, question_id)
            if question is None:
                result.failed.append(
                    {"question_id": question_id, "error": "Question not found"}
                )
                continue
            if question.graph_built:
                result.skipped.append(
                    {
                        "question_id": question_id,
                        "reason": "Graph already built",
                    }
                )
                continue
            try:
                item = await self.run_question(question_id)
            except EvidenceAbstentionError as exc:
                result.abstained.append(
                    {"question_id": question_id, "reason": str(exc)}
                )
                continue
            except Exception as exc:
                result.failed.append(
                    {"question_id": question_id, "error": str(exc)}
                )
                continue
            result.processed.append(item)
        return result

    async def resume_graph(self, run_id: str) -> ConstructionRunResult:
        """Resume only graph construction from validated prior artifacts."""
        run = self.artifacts.reopen_run(run_id, "graph_construction")
        self.dataset_version = run.dataset_version
        stored_requirements = run.model_configuration.get("requirements")
        if stored_requirements:
            self._configure_requirements(
                EvidenceSatisfactionConfig.model_validate(stored_requirements)
            )
        if run.question_id is None:
            raise RuntimeError("Cannot resume graph construction without a question")
        question = self.db.get(Question, run.question_id)
        dossiers = self.db.get_many(
            ApprovedEvidenceDossier,
            filters={"run_id": run_id, "status": ArtifactStatus.VALIDATED.value},
        )
        explanations = self.db.get_many(
            ExplanationArtifact,
            filters={"run_id": run_id, "status": ArtifactStatus.VALIDATED.value},
        )
        if question is None or not dossiers or not explanations:
            raise RuntimeError("Validated graph inputs are missing")
        OutcomeEventService(self.db).ensure_actual_outcome_alignment(question)
        dossier = max(dossiers, key=lambda item: item.created_at)
        explanation = max(explanations, key=lambda item: item.created_at)
        revision = await self._build_graph(
            run, question, dossier, explanation
        )
        completed = self.artifacts.complete_run(run.id)
        return ConstructionRunResult(
            run_id=run.id,
            question_id=question.id,
            evidence_dossier_id=dossier.id,
            explanation_id=explanation.id,
            graph_revision_id=revision.id,
            article_count=len(dossier.article_version_ids),
            event_count=len(revision.nodes),
            edge_count=len(revision.edges),
            impact_count=len(revision.outcome_impacts),
            token_usage=completed.token_usage,
            cost_usd=completed.cost_usd,
        )

    def _configure_requirements(
        self, requirements: EvidenceSatisfactionConfig
    ) -> None:
        """Bind all deterministic gates to one canonical requirement policy."""
        self.requirements = requirements
        self.monitor = QuestionMonitorService(self.db, requirements)
        self.coverage_policy = EvidenceCoverageService(self.db, requirements)
        self.graphs = ConstructionGraphService(self.db, requirements)

    async def _generate_question(
        self, run: PipelineRun, topic: str
    ) -> Question:
        attempt = self.artifacts.start_stage_attempt(
            run.id, "question_generation", f"question:{topic.strip().lower()}"
        )
        try:
            results = await self._seed_sources(topic)
            if not results:
                raise RuntimeError(f"No live search results for topic: {topic}")
            source_context = [
                {
                    "source_id": f"S{index:02d}",
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "published_date": item.get("publishedDate"),
                    "snippet": item.get("content"),
                }
                for index, item in enumerate(results[: self.max_search_results], 1)
            ]
            draft, usage = await self.runtime.run_structured(
                "QuestionGenerator",
                QUESTION_GENERATOR_INSTRUCTIONS,
                json.dumps({"topic": topic, "sources": source_context}, default=str),
                GeneratedQuestionDraft,
            )
            assert isinstance(draft, GeneratedQuestionDraft)
            question = self._question_from_draft(draft)
            self.db.save(Question, question)
            OutcomeEventService(self.db).auto_create_outcome_events(question)
            self.artifacts.bind_question(run.id, question.id)
            self._finish_success(attempt.id, [question.id], usage)
            return self.db.get(Question, question.id) or question
        except Exception as exc:
            self._finish_failure(attempt.id, "question_generation_failed", exc)
            raise

    async def _collect_evidence(
        self, run: PipelineRun, question: Question
    ) -> ApprovedEvidenceDossier:
        attempt = self.artifacts.start_stage_attempt(
            run.id, "evidence_collection", f"evidence:{question.id}"
        )
        total_usage = AgentUsage()
        try:
            market_analysis = await self._market_analysis(question)
            plan, usage = await self.runtime.run_structured(
                "EvidenceSearchPlanner",
                SEARCH_PLANNER_INSTRUCTIONS,
                json.dumps(
                    {
                        "question": self._question_payload(question),
                        "market_analysis": market_analysis,
                        "search_policy": self._search_policy_payload(question),
                    },
                    default=str,
                ),
                SearchPlanDraft,
            )
            assert isinstance(plan, SearchPlanDraft)
            total_usage = self._add_usage(total_usage, usage)

            approved_by_id: Dict[str, ArticleQualityRecord] = {}
            all_articles: Dict[str, Article] = {}
            rejected: Dict[str, List[str]] = {}
            seen_urls: set[str] = set()
            queries_used: List[str] = []
            intended_coverage: List[str] = []
            round_statistics: List[Dict[str, object]] = []
            missing_requirements: List[str] = []
            coverage: Optional[CoverageAssessmentDraft] = None
            evidence_profile = self.coverage_policy.profile_for(question)

            existing_articles = self._existing_question_articles(question)
            eligible_existing: List[Article] = []
            for article in existing_articles:
                if article.url:
                    seen_urls.add(self._normalize_url(article.url))
                if self.coverage_policy.is_hindsight_eligible(question, article):
                    eligible_existing.append(article)
                    all_articles[article.id] = article
                else:
                    rejected[article.id] = ["outside_hindsight_reporting_window"]

            existing_records = await self._clean_articles(eligible_existing)
            for record in existing_records:
                if record.status == QualityStatus.COMPLETE and record.clean_markdown:
                    approved_by_id[record.id] = record

            if approved_by_id:
                missing_requirements = self.coverage_policy.deterministic_gaps(
                    question,
                    list(approved_by_id.values()),
                )
                if not missing_requirements:
                    temporary_aliases = {
                        f"A{index:02d}": record.id
                        for index, record in enumerate(approved_by_id.values(), 1)
                    }
                    assessment, usage = await self.runtime.run_structured(
                        "EvidenceCoverageAssessor",
                        COVERAGE_ASSESSOR_INSTRUCTIONS,
                        json.dumps(
                            {
                                "question": self._question_payload(question),
                                "evidence": self._render_evidence(
                                    temporary_aliases,
                                    list(approved_by_id.values()),
                                ),
                                "requirements": self.requirements.model_dump(),
                                "evidence_profile": evidence_profile.model_dump(),
                            },
                            default=str,
                        ),
                        CoverageAssessmentDraft,
                    )
                    assert isinstance(assessment, CoverageAssessmentDraft)
                    coverage = assessment
                    total_usage = self._add_usage(total_usage, usage)
                    semantic_gaps = self.coverage_policy.semantic_gaps(coverage)
                    if not coverage.ready or semantic_gaps:
                        missing_requirements = (
                            semantic_gaps
                            or coverage.missing_evidence_needs
                            or ["coverage assessor rejected the existing evidence"]
                        )

                round_statistics.append(
                    {
                        "round": 0,
                        "source": "existing_question_evidence",
                        "fetched_new": 0,
                        "approved_new": len(approved_by_id),
                        "approved_total": len(approved_by_id),
                        "rejected_total": len(rejected),
                        "missing_requirements": missing_requirements,
                    }
                )

            for round_number in range(1, self.max_evidence_rounds + 1):
                if coverage is not None and coverage.ready and not missing_requirements:
                    break
                queries_used.extend(
                    self._build_search_query(question, item)
                    for item in self._bounded_search_queries(plan)
                )
                intended_coverage.extend(plan.intended_coverage)
                articles, round_rejected = await self._collect_search_results(
                    question,
                    plan,
                    seen_urls=seen_urls,
                    include_source_urls=round_number == 1,
                )
                rejected.update(round_rejected)
                all_articles.update({item.id: item for item in articles})
                records = await self._clean_articles(articles)
                for record in records:
                    if (
                        record.status == QualityStatus.COMPLETE
                        and record.clean_markdown
                    ):
                        approved_by_id[record.id] = record

                approved = list(approved_by_id.values())
                missing_requirements = self.coverage_policy.deterministic_gaps(
                    question,
                    approved,
                )
                coverage = None
                if not missing_requirements:
                    temporary_aliases = {
                        f"A{index:02d}": record.id
                        for index, record in enumerate(approved, 1)
                    }
                    evidence = self._render_evidence(temporary_aliases, approved)
                    assessment, usage = await self.runtime.run_structured(
                        "EvidenceCoverageAssessor",
                        COVERAGE_ASSESSOR_INSTRUCTIONS,
                        json.dumps(
                            {
                                "question": self._question_payload(question),
                                "evidence": evidence,
                                "requirements": self.requirements.model_dump(),
                                "evidence_profile": evidence_profile.model_dump(),
                            },
                            default=str,
                        ),
                        CoverageAssessmentDraft,
                    )
                    assert isinstance(assessment, CoverageAssessmentDraft)
                    coverage = assessment
                    total_usage = self._add_usage(total_usage, usage)
                    semantic_gaps = self.coverage_policy.semantic_gaps(coverage)
                    if not coverage.ready or semantic_gaps:
                        missing_requirements = (
                            semantic_gaps
                            or coverage.missing_evidence_needs
                            or ["coverage assessor rejected the evidence dossier"]
                        )

                round_statistics.append(
                    {
                        "round": round_number,
                        "fetched_new": len(articles),
                        "approved_new": sum(
                            1
                            for record in records
                            if record.id in approved_by_id
                        ),
                        "approved_total": len(approved),
                        "rejected_total": len(rejected),
                        "missing_requirements": missing_requirements,
                    }
                )
                if not missing_requirements:
                    break
                if round_number == self.max_evidence_rounds:
                    break

                plan, usage = await self.runtime.run_structured(
                    "EvidenceRecoveryPlanner",
                    SEARCH_PLANNER_INSTRUCTIONS,
                    json.dumps(
                        {
                            "question": self._question_payload(question),
                            "approved_count": len(approved),
                            "minimum_approved": evidence_profile.article_target,
                            "missing_evidence_needs": missing_requirements,
                            "prior_queries": queries_used,
                            "search_policy": self._search_policy_payload(question),
                            "instruction": (
                                "Produce new targeted queries; do not repeat prior "
                                "queries. Recover missing dates, perspectives, and "
                                "outcome evidence."
                            ),
                        },
                        default=str,
                    ),
                    SearchPlanDraft,
                )
                assert isinstance(plan, SearchPlanDraft)
                total_usage = self._add_usage(total_usage, usage)

            approved = list(approved_by_id.values())
            search_dossier = SearchDossier(
                run_id=run.id,
                question_id=question.id,
                dataset_version=self.dataset_version,
                queries=list(dict.fromkeys(queries_used)),
                selected_article_ids=[item.article_id for item in approved],
                rejected_articles=rejected,
                intended_coverage=list(dict.fromkeys(intended_coverage)),
                unresolved_gaps=missing_requirements,
                coverage_statistics={
                    "fetched": len(all_articles),
                    "approved": len(approved),
                    "minimum_required": evidence_profile.article_target,
                    "minimum_unique_sources": evidence_profile.min_unique_sources,
                    "horizon_days": evidence_profile.horizon_days,
                    "rounds_completed": len(round_statistics),
                    "rounds": round_statistics,
                },
                status=(
                    ArtifactStatus.VALIDATED
                    if not missing_requirements
                    else ArtifactStatus.REJECTED
                ),
            )
            self.db.save(SearchDossier, search_dossier)
            if missing_requirements:
                raise EvidenceAbstentionError(
                    missing_requirements,
                    len(round_statistics),
                )
            provisional = ApprovedEvidenceDossier(
                run_id=run.id,
                question_id=question.id,
                dataset_version=self.dataset_version,
                search_dossier_id=search_dossier.id,
                article_version_ids=[item.id for item in approved],
                readiness_decision="pending",
            )
            alias_map = self.artifacts.register_aliases(
                run.id,
                provisional.id,
                AliasScopeType.EVIDENCE_DOSSIER,
                AliasEntityKind.ARTICLE,
                provisional.article_version_ids,
            )
            assert coverage is not None and coverage.ready
            provisional.readiness_decision = "ready"
            provisional.coverage_summary = {
                "covered_aspects": coverage.covered_aspects,
                "rationale": coverage.rationale,
            }
            provisional.remaining_gaps = coverage.missing_evidence_needs
            dossier = self.artifacts.save_approved_dossier(provisional)
            self._link_approved_evidence(question.id, approved)
            self._finish_success(
                attempt.id,
                [search_dossier.id, dossier.id],
                total_usage,
            )
            return dossier
        except EvidenceAbstentionError as exc:
            self._finish_needs_review(
                attempt.id,
                "evidence_requirements_unmet",
                exc,
                total_usage,
            )
            raise
        except Exception as exc:
            self._finish_failure(attempt.id, "evidence_collection_failed", exc)
            raise

    def _existing_question_articles(self, question: Question) -> List[Article]:
        """Load linked snapshots across current and legacy provenance fields."""
        articles_by_id: Dict[str, Article] = {}
        for article_id in question.related_article_ids:
            article = self.db.get(Article, article_id)
            if article is not None:
                articles_by_id[article.id] = article

        for article in self.db.get_many(
            Article,
            filters={"collected_for_question_id": question.id},
        ):
            articles_by_id[article.id] = article

        for article in self.db.get_many(Article):
            related_ids = article.metadata.get("related_question_ids", [])
            if question.id in related_ids:
                articles_by_id[article.id] = article

        return list(articles_by_id.values())

    def _link_approved_evidence(
        self,
        question_id: str,
        records: List[ArticleQualityRecord],
    ) -> None:
        """Persist evidence provenance without changing question-source links."""
        with self.db.batch():
            for record in records:
                article = self.db.get(Article, record.article_id)
                if article is None:
                    continue
                if article.collected_for_question_id is None:
                    article.collected_for_question_id = question_id
                elif article.collected_for_question_id != question_id:
                    related_ids = list(
                        article.metadata.get("related_question_ids", [])
                    )
                    if question_id not in related_ids:
                        related_ids.append(question_id)
                    article.metadata["related_question_ids"] = related_ids
                self.db.save(Article, article)

    async def _synthesize_explanation(
        self,
        run: PipelineRun,
        question: Question,
        dossier: ApprovedEvidenceDossier,
    ) -> ExplanationArtifact:
        attempt = self.artifacts.start_stage_attempt(
            run.id, "explanation_synthesis", f"explanation:{dossier.id}"
        )
        try:
            evidence = self._read_dossier(run.id, dossier)
            total_usage = AgentUsage()
            validation_errors: List[str] = []
            explanation: Optional[ExplanationArtifact] = None
            required_candidates = max(self.requirements.min_graph_events - 1, 1)
            for _ in range(self.max_explanation_repairs + 1):
                candidate, usage = await self.runtime.run_structured(
                    "HindsightExplanationRepairer"
                    if validation_errors
                    else "HindsightExplanationSynthesizer",
                    EXPLANATION_INSTRUCTIONS,
                    json.dumps(
                        {
                            "question": self._question_payload(question),
                            "evidence": evidence,
                            "requirements": self.requirements.model_dump(),
                            "validation_errors": validation_errors,
                        },
                        default=str,
                    ),
                    ExplanationDraft,
                )
                assert isinstance(candidate, ExplanationDraft)
                total_usage = self._add_usage(total_usage, usage)
                if len(candidate.event_candidates) < required_candidates:
                    validation_errors = [
                        (
                            "event_candidates "
                            f"({len(candidate.event_candidates)} < "
                            f"{required_candidates})"
                        )
                    ]
                    continue
                candidate = self._canonicalize_explanation_references(
                    candidate,
                    evidence,
                )
                proposed = ExplanationArtifact(
                    run_id=run.id,
                    question_id=question.id,
                    dataset_version=self.dataset_version,
                    evidence_dossier_id=dossier.id,
                    sections=candidate.sections,
                    event_candidates=candidate.event_candidates,
                    model=self.runtime.model_id,
                    prompt_version=PROMPT_BUNDLE_VERSION,
                )
                try:
                    explanation = self.artifacts.save_validated_explanation(proposed)
                    break
                except ArtifactValidationError as exc:
                    validation_errors = exc.errors
            if explanation is None:
                raise RuntimeError(
                    "Explanation requirements not met: "
                    + ", ".join(validation_errors)
                )
            question.causal_explanation = self._render_explanation(
                explanation, evidence
            )
            self.db.save(Question, question)
            self._finish_success(attempt.id, [explanation.id], total_usage)
            return explanation
        except Exception as exc:
            self._finish_failure(attempt.id, "explanation_synthesis_failed", exc)
            raise

    async def _build_graph(
        self,
        run: PipelineRun,
        question: Question,
        dossier: ApprovedEvidenceDossier,
        explanation: ExplanationArtifact,
    ) -> GraphRevision:
        previous_attempts = self.db.get_many(
            StageAttempt,
            filters={"run_id": run.id, "stage_name": "graph_construction"},
        )
        attempt = self.artifacts.start_stage_attempt(
            run.id,
            "graph_construction",
            f"graph:{explanation.id}:{len(previous_attempts) + 1}",
        )
        total_usage = AgentUsage()
        parent_id: Optional[str] = None
        validation_errors: List[str] = []
        previous_graph: Optional[Dict[str, object]] = None
        evidence = self._read_dossier(run.id, dossier)
        try:
            for revision_number in range(self.max_graph_repairs + 1):
                revision = GraphRevision(
                    run_id=run.id,
                    question_id=question.id,
                    dataset_version=self.dataset_version,
                    explanation_artifact_id=explanation.id,
                    parent_revision_id=parent_id,
                )
                outcomes = [
                    self.db.get(Event, item_id)
                    for item_id in question.outcome_event_ids
                ]
                outcomes = [item for item in outcomes if item is not None]
                outcome_aliases = self.artifacts.register_aliases(
                    run.id,
                    revision.id,
                    AliasScopeType.GRAPH_REVISION,
                    AliasEntityKind.OUTCOME,
                    [item.id for item in outcomes],
                )
                payload = {
                    "question": self._question_payload(question),
                    "approved_evidence": evidence,
                    "explanation": explanation.model_dump(mode="json"),
                    "requirements": self.requirements.model_dump(),
                    "outcomes": [
                        {
                            "alias": alias,
                            "title": next(
                                item.title for item in outcomes if item.id == target_id
                            ),
                            "scenario": next(
                                (
                                    item.outcome_scenario.value
                                    if item.outcome_scenario
                                    else None
                                )
                                for item in outcomes
                                if item.id == target_id
                            ),
                            "is_actual_outcome": next(
                                bool(item.is_actual_outcome)
                                for item in outcomes
                                if item.id == target_id
                            ),
                        }
                        for alias, target_id in outcome_aliases.items()
                    ],
                    "validation_errors": validation_errors,
                    "previous_graph": previous_graph,
                }
                draft, usage = await self.runtime.run_structured(
                    "GraphRepairer" if validation_errors else "GraphBuilder",
                    GRAPH_REPAIR_INSTRUCTIONS
                    if validation_errors
                    else GRAPH_BUILDER_INSTRUCTIONS,
                    json.dumps(payload, default=str),
                    GraphDraft,
                )
                assert isinstance(draft, GraphDraft)
                total_usage = self._add_usage(total_usage, usage)
                revision.nodes = [
                    GraphNodeProposal.model_validate(item.model_dump())
                    for item in draft.nodes
                ]
                revision.edges = [
                    GraphEdgeProposal.model_validate(item.model_dump())
                    for item in draft.edges
                ]
                revision.outcome_impacts = [
                    OutcomeImpactProposal.model_validate(item.model_dump())
                    for item in draft.outcome_impacts
                ]
                self.db.save(GraphRevision, revision)
                try:
                    self.graphs.validate(revision)
                    committed = self.graphs.commit(revision.id)
                    self._finish_success(attempt.id, [committed.id], total_usage)
                    return committed
                except ArtifactValidationError as exc:
                    validation_errors = exc.errors
                    parent_id = revision.id
                    previous_graph = draft.model_dump(mode="json")
                    if revision_number >= self.max_graph_repairs:
                        raise
            raise RuntimeError("Graph repair budget exhausted")
        except Exception as exc:
            failed_question = self.db.get(Question, question.id)
            if failed_question is not None:
                failed_question.graph_built = False
                failed_question.graph_build_error = str(exc)
                self.db.save(Question, failed_question)
            self._finish_failure(attempt.id, "graph_construction_failed", exc)
            raise

    async def _collect_search_results(
        self,
        question: Question,
        plan: SearchPlanDraft,
        seen_urls: Optional[set[str]] = None,
        include_source_urls: bool = True,
    ) -> tuple[List[Article], Dict[str, List[str]]]:
        collector = ArticleCollectorTool(
            db=self.db,
            question_id=question.id,
            quality_processor=self.quality,
        )
        article_ids: List[str] = []
        rejected: Dict[str, List[str]] = {}
        seen_urls = seen_urls if seen_urls is not None else set()
        source_urls = self.source_urls if include_source_urls else []
        for url in source_urls:
            fetch_url = url.strip()
            normalized_url = self._normalize_url(fetch_url)
            if not normalized_url or normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)
            published, provenance = self._publication_metadata(
                {"url": fetch_url},
                question,
                explicit_source=True,
            )
            try:
                output = await asyncio.to_thread(
                    collector.forward,
                    url=fetch_url,
                    title=self._title_from_url(fetch_url),
                    source=urlparse(fetch_url).netloc or "web",
                    published_date=published,
                    domain=question.domain.value,
                )
            except Exception as exc:
                rejected[normalized_url] = [f"collection_error: {exc}"]
                continue
            if output.id in {"error", "duplicate"}:
                rejected[normalized_url] = [output.status]
            else:
                self._set_publication_date_provenance(
                    output.id,
                    provenance,
                )
                article_ids.append(output.id)
        for query in self._bounded_search_queries(plan):
            targeted_query = self._build_search_query(question, query)
            try:
                results = await asyncio.to_thread(self._search, targeted_query)
            except Exception as exc:
                rejected[f"query:{targeted_query}"] = [f"search_error: {exc}"]
                continue
            for result in results[: self.max_search_results]:
                url = str(result.get("url") or "")
                normalized_url = self._normalize_url(url)
                if not normalized_url or normalized_url in seen_urls:
                    continue
                seen_urls.add(normalized_url)
                published, provenance = self._publication_metadata(
                    result,
                    question,
                )
                try:
                    output = await asyncio.to_thread(
                        collector.forward,
                        url=url,
                        title=str(result.get("title") or "Untitled article"),
                        source=urlparse(url).netloc or "web",
                        published_date=str(published),
                        domain=question.domain.value,
                    )
                except Exception as exc:
                    rejected[normalized_url] = [f"collection_error: {exc}"]
                    continue
                if output.id in {"error", "duplicate"}:
                    rejected[normalized_url] = [output.status]
                else:
                    self._set_publication_date_provenance(
                        output.id,
                        provenance,
                    )
                    article_ids.append(output.id)
        articles = [
            self.db.get(Article, item_id)
            for item_id in dict.fromkeys(article_ids)
        ]
        eligible: List[Article] = []
        for article in articles:
            if article is None:
                continue
            if not self.coverage_policy.is_hindsight_eligible(question, article):
                rejected[article.url or article.id] = [
                    "outside_hindsight_reporting_window"
                ]
                continue
            eligible.append(article)
        return eligible, rejected

    def _set_publication_date_provenance(
        self,
        article_id: str,
        provenance: str,
    ) -> None:
        """Persist whether the collection date was observed or assumed."""
        article = self.db.get(Article, article_id)
        if article is None:
            return
        article.metadata["publication_date_provenance"] = provenance
        self.db.save(Article, article)

    @staticmethod
    def _publication_metadata(
        result: Dict[str, object],
        question: Question,
        explicit_source: bool = False,
    ) -> tuple[str, str]:
        """Resolve a reported date without hiding archive-date uncertainty."""
        reported = result.get("publishedDate")
        if reported:
            return str(reported), "search_result"
        url = str(result.get("url") or "")
        archive_match = re.search(
            r"web\.archive\.org/web/(\d{14})",
            url,
            flags=re.IGNORECASE,
        )
        if archive_match:
            captured = datetime.strptime(
                archive_match.group(1),
                "%Y%m%d%H%M%S",
            ).replace(tzinfo=timezone.utc)
            return captured.isoformat(), "archive_capture"
        provenance = (
            "assumed_resolution_explicit_source"
            if explicit_source
            else "assumed_resolution_missing_date"
        )
        return question.resolution_date.isoformat(), provenance

    def _bounded_search_queries(
        self,
        plan: SearchPlanDraft,
    ) -> List[SearchQuery]:
        """Apply a deterministic per-round query budget."""
        return plan.queries[: self.max_search_queries_per_round]

    def _article_is_temporally_eligible(
        self,
        article: Article,
        question: Question,
    ) -> bool:
        """Backward-compatible alias for the hindsight reporting policy."""
        return self.coverage_policy.is_hindsight_eligible(question, article)

    def _search_policy_payload(self, question: Question) -> Dict[str, object]:
        """Describe the bounded hindsight-search interval to planning agents."""
        latest = question.resolution_date + timedelta(
            days=self.requirements.hindsight_reporting_delay_days
        )
        return {
            "date_start": (
                question.estimated_start_time or question.resolution_date
            ).date(),
            "date_end": latest.date(),
            "resolution_date": question.resolution_date.date(),
            "ground_truth": question.ground_truth,
            "required_query_fields": [
                "evidence_need",
                "required_entities",
                "date_start",
                "date_end",
                "preferred_source_types",
            ],
        }

    def _build_search_query(
        self,
        question: Question,
        query: SearchQuery,
    ) -> str:
        """Enforce entity and date constraints on one model-proposed query."""
        terms = query.query.strip()
        lowered = terms.lower()
        for entity in query.required_entities:
            entity = entity.strip()
            if entity and entity.lower() not in lowered:
                terms += f' "{entity}"'
                lowered = terms.lower()
        policy_start = (question.estimated_start_time or question.resolution_date).date()
        policy_end = (
            question.resolution_date
            + timedelta(days=self.requirements.hindsight_reporting_delay_days)
        ).date()
        date_start = max(query.date_start or policy_start, policy_start)
        date_end = min(query.date_end or policy_end, policy_end)
        if date_start > date_end:
            date_start, date_end = policy_start, policy_end
        return " ".join(
            f"{terms} after:{date_start.isoformat()} before:{date_end.isoformat()}".split()
        )

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Canonicalize URL identity before crawl and failure caching."""
        raw = url.strip()
        if not raw:
            return ""
        parsed = urlsplit(raw)
        tracking = {
            "fbclid",
            "gclid",
            "mc_cid",
            "mc_eid",
            "ref",
        }
        query = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in tracking
        ]
        path = parsed.path.rstrip("/") or "/"
        return urlunsplit(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                path,
                urlencode(sorted(query)),
                "",
            )
        )

    async def _seed_sources(self, topic: str) -> List[Dict[str, object]]:
        """Fetch explicit live sources, falling back to web discovery."""
        if not self.source_urls:
            return await asyncio.to_thread(self._search, topic)
        fetcher = WebFetchTool()
        sources: List[Dict[str, object]] = []
        for url in self.source_urls[:3]:
            output = await asyncio.to_thread(fetcher.forward, url, 30)
            if not output.success or not output.content:
                continue
            sources.append(
                {
                    "title": self._title_from_url(url),
                    "url": url,
                    "content": output.content[:12_000],
                    "publishedDate": None,
                }
            )
        if sources:
            return sources
        return await asyncio.to_thread(self._search, topic)

    async def _market_analysis(
        self,
        question: Question,
    ) -> Dict[str, List[Dict[str, object]]]:
        """Return optional market turning points that guide evidence search."""
        empty: Dict[str, List[Dict[str, object]]] = {
            "turning_points": [],
            "lead_changes": [],
        }
        if question.source != "polymarket" or not question.metadata:
            return empty
        token_ids = question.metadata.get("clob_token_ids") or []
        if not token_ids:
            return empty
        try:
            from src.integrations.polymarket import (
                analyze_price_curve,
                get_price_history_for_market,
            )

            histories = await get_price_history_for_market(
                token_ids,
                interval="max",
                fidelity=720,
            )
            history = histories.get(token_ids[0], []) if histories else []
            if not history:
                return empty
            analysis = analyze_price_curve(
                history,
                min_turning_point_change=5.0,
                min_sharp_movement_change=10.0,
            )
        except Exception:
            return empty
        return {
            "turning_points": list(analysis.get("turning_points", []))[:5],
            "lead_changes": list(analysis.get("lead_changes", [])),
        }

    @staticmethod
    def _title_from_url(url: str) -> str:
        parsed = urlparse(url)
        path = parsed.path.strip("/").split("/")[-1]
        readable = path.replace("-", " ").replace("_", " ")
        return f"{parsed.netloc or 'Web source'}: {readable or 'article'}"[:200]

    async def _clean_articles(
        self, articles: List[Article]
    ) -> List[ArticleQualityRecord]:
        async def clean(article: Article) -> ArticleQualityRecord:
            record = self.quality.ensure_article_record(article)
            if record.status == QualityStatus.COMPLETE and record.clean_markdown:
                return record
            if not self.quality.article_is_eligible_for_cleanup(record):
                return record
            try:
                return await self.quality.clean_article(article, record)
            except Exception as exc:
                record.status = QualityStatus.FAILED
                record.metadata["cleanup_error"] = str(exc)
                self.db.save(ArticleQualityRecord, record)
                return record

        return list(await asyncio.gather(*(clean(article) for article in articles)))

    def _search(self, query: str) -> List[Dict[str, object]]:
        search = WebSearchTool()
        results: List[Dict[str, object]] = []
        seen_urls: set[str] = set()
        candidates = self._search_query_candidates(query)
        for candidate in candidates:
            candidate_results = search._get_structured_results(
                query=candidate,
                categories="news",
                language="en",
            )
            for result in candidate_results:
                url = str(result.get("url") or "")
                normalized_url = self._normalize_url(url)
                if not normalized_url or normalized_url in seen_urls:
                    continue
                seen_urls.add(normalized_url)
                results.append(result)
            if len(results) >= self.max_search_results:
                return results

        fallback = SmolWebSearchTool()
        for candidate in candidates:
            try:
                markdown = fallback.forward(query=candidate)
            except Exception:
                continue
            parsed = self._parse_markdown_search_results(markdown)
            for result in parsed:
                url = str(result.get("url") or "")
                normalized_url = self._normalize_url(url)
                if not normalized_url or normalized_url in seen_urls:
                    continue
                seen_urls.add(normalized_url)
                results.append(result)
            if len(results) >= self.max_search_results:
                break
        return results

    @staticmethod
    def _search_query_candidates(query: str) -> List[str]:
        """Return progressively simpler queries for heterogeneous search backends."""
        without_dates = re.sub(
            r"\b(?:after|before):\d{4}-\d{2}-\d{2}\b",
            " ",
            query,
            flags=re.IGNORECASE,
        )
        without_boolean_syntax = re.sub(
            r"\b(?:AND|OR)\b|[()]",
            " ",
            without_dates,
            flags=re.IGNORECASE,
        )
        without_quotes = without_boolean_syntax.replace('"', " ")
        return list(
            dict.fromkeys(
                normalized
                for candidate in (
                    query,
                    without_dates,
                    without_boolean_syntax,
                    without_quotes,
                )
                if (normalized := " ".join(candidate.split()))
            )
        )

    @staticmethod
    def _parse_markdown_search_results(markdown: str) -> List[Dict[str, object]]:
        """Recover a minimal structured result from the built-in search fallback."""
        pattern = re.compile(
            r"^\[(?P<title>[^\]]+)\]\((?P<url>https?://[^)]+)\)\s*$",
            re.MULTILINE,
        )
        matches = list(pattern.finditer(markdown))
        results: List[Dict[str, object]] = []
        for index, match in enumerate(matches):
            end = (
                matches[index + 1].start()
                if index + 1 < len(matches)
                else len(markdown)
            )
            snippet = markdown[match.end() : end].strip()
            results.append(
                {
                    "title": match.group("title"),
                    "url": match.group("url"),
                    "content": snippet,
                    "publishedDate": None,
                    "engines": ["fallback"],
                }
            )
        return results

    def _read_dossier(
        self, run_id: str, dossier: ApprovedEvidenceDossier
    ) -> List[Dict[str, object]]:
        aliases = self.artifacts.register_aliases(
            run_id,
            dossier.id,
            AliasScopeType.EVIDENCE_DOSSIER,
            AliasEntityKind.ARTICLE,
            dossier.article_version_ids,
        )
        return [
            self.artifacts.read_approved_evidence(run_id, dossier.id, alias)
            for alias in sorted(aliases)
        ]

    def _render_evidence(
        self,
        aliases: Dict[str, str],
        records: List[ArticleQualityRecord],
    ) -> List[Dict[str, object]]:
        by_id = {item.id: item for item in records}
        rendered = []
        for alias, version_id in sorted(aliases.items()):
            record = by_id[version_id]
            article = self.db.get(Article, record.article_id)
            if article is None:
                continue
            rendered.append(
                {
                    "alias": alias,
                    "article_version_id": version_id,
                    "title": article.title,
                    "source": article.source,
                    "published_date": article.published_date.isoformat(),
                    "publication_date_provenance": article.metadata.get(
                        "publication_date_provenance", "stored_article"
                    ),
                    "clean_markdown": record.clean_markdown,
                }
            )
        return rendered

    @staticmethod
    def _question_from_draft(draft: GeneratedQuestionDraft) -> Question:
        question_type = QuestionType(draft.question_type.lower())
        ground_truth: object = draft.ground_truth
        if question_type == QuestionType.BINARY:
            normalized = draft.ground_truth.strip().lower()
            if normalized not in {"yes", "no", "true", "false"}:
                raise ValueError("Binary ground truth must be yes/no or true/false")
            ground_truth = normalized in {"yes", "true"}
        if draft.estimated_start_time >= draft.resolution_date:
            raise ValueError("Question start must precede resolution")
        if draft.resolution_date > datetime.now(timezone.utc):
            raise ValueError("Construction requires an already-resolved question")
        return Question(
            id=f"q_live_{uuid4().hex[:12]}",
            question_text=draft.question_text,
            question_type=question_type,
            domain=Domain(draft.domain.lower()),
            source="construction_pipeline_v2",
            difficulty=draft.difficulty,
            resolution_date=draft.resolution_date,
            estimated_start_time=draft.estimated_start_time,
            ground_truth=ground_truth,
            context=draft.context,
            resolution_criteria=draft.resolution_criteria,
            resolution_reasoning=draft.resolution_reasoning,
            options=draft.options or None,
            related_article_ids=[],
            metadata={"workflow_version": WORKFLOW_VERSION},
        )

    @staticmethod
    def _question_payload(question: Question) -> Dict[str, object]:
        return {
            "id": question.id,
            "question": question.question_text,
            "type": question.question_type.value,
            "domain": question.domain.value,
            "forecast_start": question.estimated_start_time,
            "resolution_date": question.resolution_date,
            "ground_truth": question.ground_truth,
            "resolution_criteria": question.resolution_criteria,
            "resolution_reasoning": question.resolution_reasoning,
            "options": question.options,
        }

    @staticmethod
    def _render_explanation(
        explanation: ExplanationArtifact, evidence: List[Dict[str, object]]
    ) -> str:
        sections = [
            f"## {section.id}\n\n{section.text}\n\n"
            + " ".join(f"[{alias}]" for alias in section.citation_aliases)
            for section in explanation.sections
        ]
        references = [
            f"[{item['alias']}] {item['title']} ({item['url']})" for item in evidence
        ]
        return "\n\n".join(sections + ["## Sources\n\n" + "\n".join(references)])

    def _finish_success(
        self, attempt_id: str, artifact_ids: List[str], usage: AgentUsage
    ) -> None:
        self.artifacts.finish_stage_attempt(
            attempt_id,
            StageAttemptStatus.SUCCEEDED,
            output_artifact_ids=artifact_ids,
            token_usage=usage.total_tokens,
            cost_usd=usage.cost_usd,
        )

    def _finish_failure(self, attempt_id: str, code: str, exc: Exception) -> None:
        self.artifacts.finish_stage_attempt(
            attempt_id,
            StageAttemptStatus.TERMINAL_FAILURE,
            failure_code=code,
            diagnostic=str(exc),
        )

    def _finish_needs_review(
        self,
        attempt_id: str,
        code: str,
        exc: Exception,
        usage: AgentUsage,
    ) -> None:
        self.artifacts.finish_stage_attempt(
            attempt_id,
            StageAttemptStatus.NEEDS_REVIEW,
            failure_code=code,
            diagnostic=str(exc),
            token_usage=usage.total_tokens,
            cost_usd=usage.cost_usd,
        )

    @staticmethod
    def _canonicalize_explanation_references(
        draft: ExplanationDraft,
        evidence: List[Dict[str, object]],
    ) -> ExplanationDraft:
        """Resolve redundant version IDs from approved article aliases."""
        version_by_alias = {
            str(item["alias"]): str(item["article_version_id"])
            for item in evidence
        }
        canonical = draft.model_copy(deep=True)
        for event in canonical.event_candidates:
            for reference in event.evidence_refs:
                version_id = version_by_alias.get(reference.article_alias)
                if version_id is not None:
                    reference.article_version_id = version_id
        return canonical

    @staticmethod
    def _add_usage(left: AgentUsage, right: AgentUsage) -> AgentUsage:
        return AgentUsage(
            input_tokens=left.input_tokens + right.input_tokens,
            output_tokens=left.output_tokens + right.output_tokens,
            total_tokens=left.total_tokens + right.total_tokens,
            requests=left.requests + right.requests,
            cost_usd=left.cost_usd + right.cost_usd,
        )
