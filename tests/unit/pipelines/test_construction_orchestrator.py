"""End-to-end persistence tests for the construction orchestrator."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Type

import pytest
from pydantic import BaseModel

from src.config.pipeline import EvidenceSatisfactionConfig
from src.domain.models import (
    Article,
    ArticleQualityRecord,
    CausalHypothesis,
    Domain,
    Event,
    EventOutcomeImpact,
    GraphRevision,
    ImpactDirection,
    PipelineRun,
    QualityStatus,
    Question,
    SearchDossier,
)
from src.pipelines.construction.models import (
    AgentUsage,
    CoverageAssessmentDraft,
    ExplanationDraft,
    GeneratedQuestionDraft,
    GraphDraft,
    SearchPlanDraft,
)
from src.pipelines.construction.orchestrator import ConstructionPipeline
from src.services.pipeline_artifact_service import ArtifactValidationError
from src.services.question_monitor_service import QuestionMonitorService


class FakeRuntime:
    """Return schema-valid outputs while deriving aliases from live artifacts."""

    model_id = "fake/structured"

    async def run_structured(
        self,
        name: str,
        instructions: str,
        user_input: str,
        output_type: Type[BaseModel],
        max_turns: int = 4,
    ) -> tuple[BaseModel, AgentUsage]:
        payload = json.loads(user_input)
        if output_type is GeneratedQuestionDraft:
            output = GeneratedQuestionDraft(
                question_text="Did the test organization publish the resolved result?",
                question_type="binary",
                domain="general",
                difficulty=2,
                resolution_date=datetime(2024, 2, 1, tzinfo=timezone.utc),
                estimated_start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
                resolution_criteria="The official publication reports the result.",
                ground_truth="yes",
                resolution_reasoning="The supplied reporting confirms publication.",
            )
        elif output_type is SearchPlanDraft:
            output = SearchPlanDraft(
                queries=[
                    {"query": "test result", "rationale": "resolution"},
                    {"query": "test timeline", "rationale": "timeline"},
                ],
                intended_coverage=["outcome", "timeline"],
            )
        elif output_type is CoverageAssessmentDraft:
            output = CoverageAssessmentDraft(
                ready=True,
                covered_aspects=["outcome", "timeline"],
                rationale="Three independent snapshots cover both aspects.",
            )
        elif output_type is ExplanationDraft:
            evidence = payload["evidence"]
            output = ExplanationDraft(
                sections=[
                    {
                        "id": "Resolution",
                        "text": "The result followed two dated developments.",
                        "citation_aliases": ["A01", "A02"],
                    }
                ],
                event_candidates=[
                    {
                        "alias": "E01",
                        "title": "Initial development",
                        "description": (
                            "The organization announced the initial development."
                        ),
                        "occurred_date": "2024-01-10T00:00:00Z",
                        "evidence_refs": [
                            {
                                "article_alias": "A01",
                                "article_version_id": evidence[0]["article_version_id"],
                                "support_type": "direct",
                            }
                        ],
                    },
                    {
                        "alias": "E02",
                        "title": "Final development",
                        "description": (
                            "The organization confirmed the final development."
                        ),
                        "occurred_date": "2024-01-20T00:00:00Z",
                        "evidence_refs": [
                            {
                                "article_alias": "A02",
                                "article_version_id": evidence[1]["article_version_id"],
                                "support_type": "direct",
                            }
                        ],
                    },
                ],
            )
        elif output_type is GraphDraft:
            actual_outcome_alias = next(
                item["alias"]
                for item in payload["outcomes"]
                if item["is_actual_outcome"]
            )
            output = GraphDraft(
                nodes=[
                    {
                        "alias": "E01",
                        "title": "Initial development",
                        "description": (
                            "The organization announced the initial development."
                        ),
                        "domain": "general",
                        "event_type": "milestone",
                        "occurred_date": "2024-01-10T00:00:00Z",
                        "evidence_aliases": ["A01"],
                    },
                    {
                        "alias": "E02",
                        "title": "Final development",
                        "description": (
                            "The organization confirmed the final development."
                        ),
                        "domain": "general",
                        "event_type": "milestone",
                        "occurred_date": "2024-01-20T00:00:00Z",
                        "evidence_aliases": ["A02"],
                    },
                ],
                edges=[
                    {
                        "source_alias": "E01",
                        "target_alias": "E02",
                        "relation": "enables",
                        "reasoning": "The initial step enabled confirmation.",
                        "strength": 0.7,
                        "confidence": 0.8,
                        "evidence_aliases": ["A01", "A02"],
                    },
                    {
                        "source_alias": "E02",
                        "target_alias": actual_outcome_alias,
                        "relation": "causes",
                        "reasoning": "Confirmation established the outcome.",
                        "strength": 0.9,
                        "confidence": 0.9,
                        "evidence_aliases": ["A02"],
                    },
                ],
                outcome_impacts=[
                    {
                        "event_alias": alias,
                        "outcome_alias": outcome["alias"],
                        "direction": (
                            "positive"
                            if outcome["is_actual_outcome"]
                            else "negative"
                        ),
                        "magnitude": 0.6,
                        "confidence": 0.8,
                        "reasoning": "This development supported the resolved outcome.",
                        "evidence_aliases": [article_alias],
                    }
                    for alias, article_alias in (("E01", "A01"), ("E02", "A02"))
                    for outcome in payload["outcomes"]
                ],
            )
        else:
            raise AssertionError(f"Unexpected output type: {output_type}")
        return output, AgentUsage(total_tokens=10, requests=1)


class RepairingFakeRuntime(FakeRuntime):
    """Return one undersized event inventory before repairing it."""

    def __init__(self) -> None:
        self.explanation_calls = 0

    async def run_structured(
        self,
        name: str,
        instructions: str,
        user_input: str,
        output_type: Type[BaseModel],
        max_turns: int = 4,
    ) -> tuple[BaseModel, AgentUsage]:
        output, usage = await super().run_structured(
            name,
            instructions,
            user_input,
            output_type,
            max_turns,
        )
        if output_type is ExplanationDraft:
            self.explanation_calls += 1
            if self.explanation_calls == 1:
                assert isinstance(output, ExplanationDraft)
                output.event_candidates = output.event_candidates[:1]
        return output, usage


class GraphRepairingFakeRuntime(FakeRuntime):
    """Require the rejected graph to be supplied to the repair call."""

    def __init__(self) -> None:
        self.graph_calls = 0

    async def run_structured(
        self,
        name: str,
        instructions: str,
        user_input: str,
        output_type: Type[BaseModel],
        max_turns: int = 4,
    ) -> tuple[BaseModel, AgentUsage]:
        output, usage = await super().run_structured(
            name,
            instructions,
            user_input,
            output_type,
            max_turns,
        )
        if output_type is GraphDraft:
            self.graph_calls += 1
            payload = json.loads(user_input)
            if self.graph_calls == 1:
                assert isinstance(output, GraphDraft)
                output.outcome_impacts = output.outcome_impacts[:1]
            else:
                assert payload["previous_graph"] is not None
                assert any(
                    error.startswith("missing_outcome_impact:E02:")
                    for error in payload["validation_errors"]
                )
                assert name == "GraphRepairer"
        return output, usage


class TemporalGraphRepairingFakeRuntime(FakeRuntime):
    """Return a temporally invalid graph before correcting it."""

    def __init__(self) -> None:
        self.graph_calls = 0

    async def run_structured(
        self,
        name: str,
        instructions: str,
        user_input: str,
        output_type: Type[BaseModel],
        max_turns: int = 4,
    ) -> tuple[BaseModel, AgentUsage]:
        output, usage = await super().run_structured(
            name,
            instructions,
            user_input,
            output_type,
            max_turns,
        )
        if output_type is GraphDraft:
            self.graph_calls += 1
            payload = json.loads(user_input)
            if self.graph_calls == 1:
                assert isinstance(output, GraphDraft)
                output.nodes[0].occurred_date = datetime(
                    2024, 3, 1, tzinfo=timezone.utc
                )
            else:
                assert "event_after_resolution:E01" in payload[
                    "validation_errors"
                ]
                assert "non_chronological_edge:E01->E02" in payload[
                    "validation_errors"
                ]
        return output, usage


class ComplementRepairingFakeRuntime(FakeRuntime):
    """Return inconsistent binary impacts before correcting them."""

    def __init__(self) -> None:
        self.graph_calls = 0

    async def run_structured(
        self,
        name: str,
        instructions: str,
        user_input: str,
        output_type: Type[BaseModel],
        max_turns: int = 4,
    ) -> tuple[BaseModel, AgentUsage]:
        output, usage = await super().run_structured(
            name,
            instructions,
            user_input,
            output_type,
            max_turns,
        )
        if output_type is GraphDraft:
            self.graph_calls += 1
            payload = json.loads(user_input)
            if self.graph_calls == 1:
                assert isinstance(output, GraphDraft)
                output.outcome_impacts[1].direction = ImpactDirection.POSITIVE
            else:
                assert any(
                    error.startswith("non_complementary_binary_impacts:E01")
                    for error in payload["validation_errors"]
                )
        return output, usage


class StubConstructionPipeline(ConstructionPipeline):
    """Replace network collection while retaining real quality artifacts."""

    def _search(self, query: str) -> List[dict[str, object]]:
        return [{"title": "Seed", "url": "https://example.test", "content": query}]

    async def _collect_search_results(self, question, plan, **kwargs):
        round_number = getattr(self, "collection_rounds", 0) + 1
        self.collection_rounds = round_number
        start = (round_number - 1) * 3
        articles = []
        for index in range(start, start + 3):
            article = Article(
                id=f"article-{index}",
                title=f"Evidence article {index}",
                content=("Substantive evidence sentence. " * 20),
                url=f"https://example.test/{index}",
                source="example.test",
                published_date=datetime(2024, 1, 10 + index, tzinfo=timezone.utc),
                domain=Domain.GENERAL,
                collected_for_question_id=question.id,
            )
            self.db.save(Article, article)
            articles.append(article)
        return articles, {}

    async def _clean_articles(self, articles):
        records = []
        for article in articles:
            record = self.quality.process_article(article)
            record.clean_markdown = article.content
            record.status = QualityStatus.COMPLETE
            self.db.save(ArticleQualityRecord, record)
            records.append(record)
        return records


class StalledConstructionPipeline(StubConstructionPipeline):
    """Return the same article in every recovery round."""

    async def _collect_search_results(self, question, plan, **kwargs):
        self.collection_rounds = getattr(self, "collection_rounds", 0) + 1
        article = Article(
            id="stalled-article",
            title="Only available evidence article",
            content=("Substantive evidence sentence. " * 20),
            url="https://example.test/stalled",
            source="example.test",
            published_date=datetime(2024, 1, 10, tzinfo=timezone.utc),
            domain=Domain.GENERAL,
            collected_for_question_id=question.id,
        )
        self.db.save(Article, article)
        return [article], {}


def test_search_simplifies_backend_incompatible_date_operators(
    monkeypatch,
) -> None:
    calls = []

    class FakeWebSearchTool:
        def _get_structured_results(self, query, **kwargs):
            del kwargs
            calls.append(query)
            if "after:" in query:
                return []
            return [{"url": "https://example.test/result", "title": "Result"}]

    monkeypatch.setattr(
        "src.pipelines.construction.orchestrator.WebSearchTool",
        FakeWebSearchTool,
    )
    pipeline = object.__new__(ConstructionPipeline)
    pipeline.max_search_results = 1

    results = pipeline._search(
        '"Donald Trump" AND "2024 election" '
        "after:2024-11-05 before:2024-11-08"
    )

    assert [item["url"] for item in results] == [
        "https://example.test/result"
    ]
    assert len(calls) == 2
    assert "after:" not in calls[1]


@pytest.mark.asyncio
async def test_constructs_question_evidence_and_graph_in_fresh_database(
    tmp_path: Path,
) -> None:
    pipeline = StubConstructionPipeline(
        db_path=tmp_path / "fresh.db",
        runtime=FakeRuntime(),
        requirements=EvidenceSatisfactionConfig(
            min_articles=3,
            min_graph_events=3,
            min_graph_depth=2,
        ),
    )

    result = await pipeline.run("resolved test event")

    run = pipeline.db.get(PipelineRun, result.run_id)
    question = pipeline.db.get(Question, result.question_id)
    revision = pipeline.db.get(GraphRevision, result.graph_revision_id)
    events = pipeline.db.get_many(
        Event, filters={"extracted_for_question_id": result.question_id}
    )
    assert run is not None and run.status.value == "complete"
    assert question is not None and question.graph_built is True
    assert revision is not None and revision.status.value == "committed"
    assert revision.validation_results["graph_depth"] == 2
    assert revision.validation_results["total_event_count"] == 3
    assert run.model_configuration["requirements"]["min_articles"] == 3
    assert run.model_configuration["max_evidence_rounds"] == 3
    dossiers = pipeline.db.get_many(SearchDossier)
    assert dossiers[0].coverage_statistics["rounds_completed"] == 1
    assert result.article_count == 3
    assert result.event_count == 2
    assert len([item for item in events if not item.is_outcome]) == 2


@pytest.mark.asyncio
async def test_constructs_backward_artifacts_for_existing_question(
    tmp_path: Path,
) -> None:
    pipeline = StubConstructionPipeline(
        db_path=tmp_path / "existing.db",
        runtime=FakeRuntime(),
        requirements=EvidenceSatisfactionConfig(
            min_articles=3,
            min_graph_events=3,
            min_graph_depth=2,
        ),
    )
    question = Question(
        id="existing-question",
        question_text="Did the test organization publish the resolved result?",
        question_type="binary",
        domain=Domain.GENERAL,
        source="polymarket",
        difficulty=2,
        estimated_start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolution_date=datetime(2024, 2, 1, tzinfo=timezone.utc),
        ground_truth=True,
    )
    pipeline.db.save(Question, question)

    result = await pipeline.run_question(question.id)

    stored = pipeline.db.get(Question, question.id)
    run = pipeline.db.get(PipelineRun, result.run_id)
    outcomes = [
        event
        for event in pipeline.db.get_many(
            Event, filters={"extracted_for_question_id": question.id}
        )
        if event.is_outcome
    ]
    hypotheses = pipeline.db.get_many(
        CausalHypothesis,
        filters={
            "discovered_by_question_ids__like": f'%"{question.id}"%'
        },
    )
    impacts = pipeline.db.get_many(
        EventOutcomeImpact,
        filters={"question_id": question.id},
    )
    assert result.question_id == question.id
    assert result.impact_count == 4
    assert stored is not None and stored.graph_built is True
    assert run is not None
    assert run.model_configuration["entrypoint"] == "existing_question"
    assert len(outcomes) == 2
    assert sum(bool(event.is_actual_outcome) for event in outcomes) == 1
    assert len(hypotheses) == 2
    assert len(impacts) == 4
    assert {impact.outcome_event_id for impact in impacts} == {
        outcome.id for outcome in outcomes
    }
    monitor = QuestionMonitorService(pipeline.db, pipeline.requirements)
    assert monitor.check_satisfaction(question.id).is_satisfied
    assert monitor.check_graph_satisfaction(question.id).is_satisfied


@pytest.mark.asyncio
async def test_existing_question_reuses_eligible_snapshots_before_search(
    tmp_path: Path,
) -> None:
    pipeline = StubConstructionPipeline(
        db_path=tmp_path / "existing-evidence.db",
        runtime=FakeRuntime(),
        requirements=EvidenceSatisfactionConfig(
            min_articles=3,
            min_graph_events=3,
            min_graph_depth=2,
        ),
    )
    question = Question(
        id="existing-evidence-question",
        question_text="Did the test organization publish the resolved result?",
        question_type="binary",
        domain=Domain.GENERAL,
        source="polymarket",
        difficulty=2,
        estimated_start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolution_date=datetime(2024, 2, 1, tzinfo=timezone.utc),
        ground_truth=True,
        related_article_ids=["existing-article-0"],
    )
    pipeline.db.save(Question, question)
    for index in range(3):
        pipeline.db.save(
            Article,
            Article(
                id=f"existing-article-{index}",
                title=f"Existing evidence article {index}",
                content="Substantive existing evidence sentence. " * 20,
                url=f"https://example.test/existing/{index}",
                source="example.test",
                published_date=datetime(2024, 1, 10 + index, tzinfo=timezone.utc),
                domain=Domain.GENERAL,
                collected_for_question_id=question.id,
            ),
        )
    pipeline.db.save(
        Article,
        Article(
            id="post-resolution-article",
            title="Post resolution retrospective article",
            content="Substantive retrospective evidence sentence. " * 20,
            url="https://example.test/existing/retrospective",
            source="example.test",
            published_date=datetime(2024, 2, 2, tzinfo=timezone.utc),
            domain=Domain.GENERAL,
            collected_for_question_id=question.id,
        ),
    )

    result = await pipeline.run_question(question.id)

    dossier = pipeline.db.get_many(SearchDossier)[0]
    stored = pipeline.db.get(Question, question.id)
    assert result.article_count == 3
    assert stored is not None
    assert stored.related_article_ids == ["existing-article-0"]
    assert getattr(pipeline, "collection_rounds", 0) == 0
    assert dossier.rejected_articles["post-resolution-article"] == [
        "published_after_resolution"
    ]
    assert dossier.coverage_statistics["rounds"][0]["round"] == 0


@pytest.mark.asyncio
async def test_existing_question_batch_isolates_question_failures(
    tmp_path: Path,
) -> None:
    pipeline = StubConstructionPipeline(
        db_path=tmp_path / "batch.db",
        runtime=FakeRuntime(),
        requirements=EvidenceSatisfactionConfig(
            min_articles=3,
            min_graph_events=3,
            min_graph_depth=2,
        ),
    )
    question = Question(
        id="batch-question",
        question_text="Did the test organization publish the resolved result?",
        question_type="binary",
        domain=Domain.GENERAL,
        source="polymarket",
        difficulty=2,
        estimated_start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolution_date=datetime(2024, 2, 1, tzinfo=timezone.utc),
        ground_truth=True,
    )
    pipeline.db.save(Question, question)

    result = await pipeline.run_questions(
        ["missing-question", question.id]
    )

    assert [item.question_id for item in result.processed] == [question.id]
    assert result.failed == [
        {
            "question_id": "missing-question",
            "error": "Question not found",
        }
    ]


def test_article_temporal_eligibility_uses_resolution_day() -> None:
    question = Question(
        id="temporal-question",
        question_text="Did the test organization publish the resolved result?",
        question_type="binary",
        domain=Domain.GENERAL,
        source="test",
        difficulty=2,
        estimated_start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolution_date=datetime(2024, 2, 1, 12, tzinfo=timezone.utc),
        ground_truth=True,
    )
    article = Article(
        id="article-after-resolution",
        title="Retrospective article",
        content="Substantive retrospective article content. " * 10,
        url="https://example.test/retrospective",
        source="example.test",
        published_date=datetime(2024, 2, 2, tzinfo=timezone.utc),
        domain=Domain.GENERAL,
    )

    assert not ConstructionPipeline._article_is_temporally_eligible(
        article, question
    )
    article.published_date = datetime(2024, 2, 1, 23, tzinfo=timezone.utc)
    assert ConstructionPipeline._article_is_temporally_eligible(
        article, question
    )


@pytest.mark.asyncio
async def test_polymarket_analysis_is_available_to_search_planning(
    monkeypatch,
) -> None:
    async def fake_history(token_ids, **kwargs):
        del kwargs
        return {token_ids[0]: [{"t": 1, "p": 0.4}]}

    def fake_analysis(history, **kwargs):
        del history, kwargs
        return {
            "turning_points": [{"timestamp": 1, "type": "peak"}],
            "lead_changes": [{"timestamp": 2, "direction": "above"}],
        }

    monkeypatch.setattr(
        "src.integrations.polymarket.get_price_history_for_market",
        fake_history,
    )
    monkeypatch.setattr(
        "src.integrations.polymarket.analyze_price_curve",
        fake_analysis,
    )
    pipeline = object.__new__(ConstructionPipeline)
    question = Question(
        id="market-question",
        question_text="Did the test organization publish the resolved result?",
        question_type="binary",
        domain=Domain.GENERAL,
        source="polymarket",
        difficulty=2,
        estimated_start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolution_date=datetime(2024, 2, 1, tzinfo=timezone.utc),
        ground_truth=True,
        metadata={"clob_token_ids": ["token-1"]},
    )

    result = await pipeline._market_analysis(question)

    assert result["turning_points"] == [{"timestamp": 1, "type": "peak"}]
    assert result["lead_changes"] == [
        {"timestamp": 2, "direction": "above"}
    ]


@pytest.mark.asyncio
async def test_repairs_undersized_explanation_before_graph_build(
    tmp_path: Path,
) -> None:
    runtime = RepairingFakeRuntime()
    pipeline = StubConstructionPipeline(
        db_path=tmp_path / "repair.db",
        runtime=runtime,
        requirements=EvidenceSatisfactionConfig(
            min_articles=3,
            min_graph_events=3,
            min_graph_depth=2,
        ),
    )

    result = await pipeline.run("resolved test event")

    assert runtime.explanation_calls == 2
    assert result.event_count == 2


@pytest.mark.asyncio
async def test_graph_repair_receives_rejected_graph(
    tmp_path: Path,
) -> None:
    runtime = GraphRepairingFakeRuntime()
    pipeline = StubConstructionPipeline(
        db_path=tmp_path / "graph-repair.db",
        runtime=runtime,
        requirements=EvidenceSatisfactionConfig(
            min_articles=3,
            min_graph_events=3,
            min_graph_depth=2,
        ),
    )

    result = await pipeline.run("resolved test event")

    assert runtime.graph_calls == 2
    assert result.impact_count == 4


@pytest.mark.asyncio
async def test_graph_repair_enforces_resolution_date_and_edge_order(
    tmp_path: Path,
) -> None:
    runtime = TemporalGraphRepairingFakeRuntime()
    pipeline = StubConstructionPipeline(
        db_path=tmp_path / "temporal-graph-repair.db",
        runtime=runtime,
        requirements=EvidenceSatisfactionConfig(
            min_articles=3,
            min_graph_events=3,
            min_graph_depth=2,
        ),
    )

    result = await pipeline.run("resolved test event")

    assert runtime.graph_calls == 2
    assert result.event_count == 2


@pytest.mark.asyncio
async def test_graph_repair_enforces_complementary_binary_impacts(
    tmp_path: Path,
) -> None:
    runtime = ComplementRepairingFakeRuntime()
    pipeline = StubConstructionPipeline(
        db_path=tmp_path / "complement-graph-repair.db",
        runtime=runtime,
        requirements=EvidenceSatisfactionConfig(
            min_articles=3,
            min_graph_events=3,
            min_graph_depth=2,
        ),
    )

    result = await pipeline.run("resolved test event")

    assert runtime.graph_calls == 2
    assert result.impact_count == 4


@pytest.mark.asyncio
async def test_terminal_graph_failure_is_visible_on_question(
    tmp_path: Path,
) -> None:
    pipeline = StubConstructionPipeline(
        db_path=tmp_path / "terminal-graph-failure.db",
        runtime=GraphRepairingFakeRuntime(),
        requirements=EvidenceSatisfactionConfig(
            min_articles=3,
            min_graph_events=3,
            min_graph_depth=2,
        ),
        max_graph_repairs=0,
    )

    with pytest.raises(ArtifactValidationError, match="missing_outcome_impact"):
        await pipeline.run("resolved test event")

    question = pipeline.db.get_many(Question)[0]
    assert question.graph_built is False
    assert question.graph_build_error is not None
    assert "missing_outcome_impact" in question.graph_build_error


@pytest.mark.asyncio
async def test_collects_more_evidence_before_continuing(
    tmp_path: Path,
) -> None:
    pipeline = StubConstructionPipeline(
        db_path=tmp_path / "evidence-recovery.db",
        runtime=FakeRuntime(),
        requirements=EvidenceSatisfactionConfig(
            min_articles=5,
            min_graph_events=3,
            min_graph_depth=2,
        ),
        max_evidence_rounds=2,
    )

    result = await pipeline.run("resolved test event")

    dossiers = pipeline.db.get_many(SearchDossier)
    assert result.article_count == 6
    assert pipeline.collection_rounds == 2
    assert dossiers[0].status.value == "validated"
    assert dossiers[0].coverage_statistics["rounds_completed"] == 2
    assert dossiers[0].coverage_statistics["rounds"][0][
        "missing_requirements"
    ] == ["articles (3 < 5)"]


@pytest.mark.asyncio
async def test_persists_exhausted_evidence_recovery(
    tmp_path: Path,
) -> None:
    pipeline = StalledConstructionPipeline(
        db_path=tmp_path / "evidence-exhausted.db",
        runtime=FakeRuntime(),
        requirements=EvidenceSatisfactionConfig(
            min_articles=3,
            min_graph_events=3,
            min_graph_depth=2,
        ),
        max_evidence_rounds=2,
    )

    with pytest.raises(
        RuntimeError,
        match="Evidence requirements not met after 2 collection rounds",
    ):
        await pipeline.run("resolved test event")

    dossiers = pipeline.db.get_many(SearchDossier)
    assert pipeline.collection_rounds == 2
    assert dossiers[0].status.value == "rejected"
    assert dossiers[0].unresolved_gaps == ["articles (1 < 3)"]
