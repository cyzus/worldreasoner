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
    Domain,
    Event,
    GraphRevision,
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
            outcome_alias = payload["outcomes"][0]["alias"]
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
                        "target_alias": outcome_alias,
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
                        "outcome_alias": outcome_alias,
                        "direction": "positive",
                        "magnitude": 0.6,
                        "confidence": 0.8,
                        "reasoning": "This development supported the resolved outcome.",
                        "evidence_aliases": [article_alias],
                    }
                    for alias, article_alias in (("E01", "A01"), ("E02", "A02"))
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
