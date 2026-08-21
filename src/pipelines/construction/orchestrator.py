"""Resumable, code-controlled benchmark construction workflow."""

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Protocol, Type
from urllib.parse import urlparse
from uuid import uuid4

from pydantic import BaseModel
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


class ConstructionPipeline:
    """Orchestrate bounded specialists around deterministic persistence gates."""

    def __init__(
        self,
        db_path: Path,
        runtime: StructuredRuntime,
        dataset_version: str = "v2-live",
        max_search_results: int = 5,
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
            plan, usage = await self.runtime.run_structured(
                "EvidenceSearchPlanner",
                SEARCH_PLANNER_INSTRUCTIONS,
                json.dumps(self._question_payload(question), default=str),
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

            for round_number in range(1, self.max_evidence_rounds + 1):
                queries_used.extend(item.query for item in plan.queries)
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
                missing_requirements = (
                    self.monitor.evaluate_article_count_requirement(len(approved))
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
                            },
                            default=str,
                        ),
                        CoverageAssessmentDraft,
                    )
                    assert isinstance(assessment, CoverageAssessmentDraft)
                    coverage = assessment
                    total_usage = self._add_usage(total_usage, usage)
                    if not coverage.ready:
                        missing_requirements = coverage.missing_evidence_needs or [
                            "coverage assessor rejected the evidence dossier"
                        ]

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
                            "minimum_approved": self.requirements.min_articles,
                            "missing_evidence_needs": missing_requirements,
                            "prior_queries": queries_used,
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
                    "minimum_required": self.requirements.min_articles,
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
                raise RuntimeError(
                    "Evidence requirements not met after "
                    f"{len(round_statistics)} collection rounds: "
                    + ", ".join(missing_requirements)
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
            question.related_article_ids = [item.article_id for item in approved]
            self.db.save(Question, question)
            self._finish_success(
                attempt.id,
                [search_dossier.id, dossier.id],
                total_usage,
            )
            return dossier
        except Exception as exc:
            self._finish_failure(attempt.id, "evidence_collection_failed", exc)
            raise

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
            draft: Optional[ExplanationDraft] = None
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
                if len(candidate.event_candidates) >= required_candidates:
                    draft = candidate
                    break
                validation_errors = [
                    (
                        "event_candidates "
                        f"({len(candidate.event_candidates)} < {required_candidates})"
                    )
                ]
            if draft is None:
                raise RuntimeError(
                    "Explanation requirements not met: "
                    + ", ".join(validation_errors)
                )
            explanation = ExplanationArtifact(
                run_id=run.id,
                question_id=question.id,
                dataset_version=self.dataset_version,
                evidence_dossier_id=dossier.id,
                sections=draft.sections,
                event_candidates=draft.event_candidates,
                model=self.runtime.model_id,
                prompt_version=PROMPT_BUNDLE_VERSION,
            )
            explanation = self.artifacts.save_validated_explanation(explanation)
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
                        }
                        for alias, target_id in outcome_aliases.items()
                    ],
                    "validation_errors": validation_errors,
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
                    if revision_number >= self.max_graph_repairs:
                        raise
            raise RuntimeError("Graph repair budget exhausted")
        except Exception as exc:
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
            normalized_url = url.strip()
            if not normalized_url or normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)
            try:
                output = await asyncio.to_thread(
                    collector.forward,
                    url=normalized_url,
                    title=self._title_from_url(normalized_url),
                    source=urlparse(normalized_url).netloc or "web",
                    published_date=question.resolution_date.isoformat(),
                    domain=question.domain.value,
                )
            except Exception as exc:
                rejected[normalized_url] = [f"collection_error: {exc}"]
                continue
            if output.id in {"error", "duplicate"}:
                rejected[normalized_url] = [output.status]
            else:
                article_ids.append(output.id)
        for query in plan.queries:
            try:
                results = await asyncio.to_thread(self._search, query.query)
            except Exception as exc:
                rejected[f"query:{query.query}"] = [f"search_error: {exc}"]
                continue
            for result in results[: self.max_search_results]:
                url = str(result.get("url") or "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                published = (
                    result.get("publishedDate")
                    or question.resolution_date.isoformat()
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
                    rejected[url] = [f"collection_error: {exc}"]
                    continue
                if output.id in {"error", "duplicate"}:
                    rejected[url] = [output.status]
                else:
                    article_ids.append(output.id)
        if len(set(article_ids)) < self.requirements.min_articles:
            recovery_query = f"{question.question_text} result timeline key events"
            try:
                results = await asyncio.to_thread(self._search, recovery_query)
            except Exception as exc:
                rejected[f"query:{recovery_query}"] = [f"search_error: {exc}"]
                results = []
            for result in results[: max(self.max_search_results, 4)]:
                url = str(result.get("url") or "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                published = (
                    result.get("publishedDate")
                    or question.resolution_date.isoformat()
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
                    rejected[url] = [f"collection_error: {exc}"]
                    continue
                if output.id in {"error", "duplicate"}:
                    rejected[url] = [output.status]
                else:
                    article_ids.append(output.id)
        articles = [
            self.db.get(Article, item_id)
            for item_id in dict.fromkeys(article_ids)
        ]
        return [item for item in articles if item is not None], rejected

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
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
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
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
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
        )

    def _finish_failure(self, attempt_id: str, code: str, exc: Exception) -> None:
        self.artifacts.finish_stage_attempt(
            attempt_id,
            StageAttemptStatus.TERMINAL_FAILURE,
            failure_code=code,
            diagnostic=str(exc),
        )

    @staticmethod
    def _add_usage(left: AgentUsage, right: AgentUsage) -> AgentUsage:
        return AgentUsage(
            input_tokens=left.input_tokens + right.input_tokens,
            output_tokens=left.output_tokens + right.output_tokens,
            total_tokens=left.total_tokens + right.total_tokens,
            requests=left.requests + right.requests,
        )
