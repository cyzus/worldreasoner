"""Tests for the modular v2 evidence-quality passes."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest
import typer

from src.cli.commands.dataset import clean_articles
from src.core.database import GenericDatabase
from src.domain.models import (
    Article,
    ArticleQualityFlag,
    ArticleQualityRecord,
    DatasetRepairRecord,
    Domain,
    Event,
    EventEvidenceExtraction,
    EventEvidenceVerification,
    EventStatus,
    EventType,
    RepairAction,
)
from src.services.dataset_versioning import DatasetVersionService
from src.services.evidence_quality.article_normalizer import (
    ArticleNormalizer,
    passage_is_traceable,
)
from src.services.evidence_quality.event_grounding import (
    EventEvidenceExtractor,
    EventEvidenceVerifier,
)
from src.services.evidence_quality.article_cleaner import measure_cleaning_fidelity
from src.services.evidence_quality.llm_client import LiteLLMStructuredClient
from src.services.evidence_quality.service import EvidenceQualityService


class FakeStructuredLLM:
    """Deterministic structured client used to isolate LLM pass behavior."""

    def __init__(self, model_name: str, responses: List[Dict[str, Any]]) -> None:
        self.model_name = model_name
        self.responses = responses

    async def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> Dict[str, Any]:
        del system_prompt, user_prompt
        return self.responses.pop(0)


class FakeLiteLLMClient:
    """Minimal LiteLLM client stub for response-shape compatibility tests."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.llm_config = {"model": "fake-model"}

    async def acomplete(self, messages, response_format=None) -> str:
        del messages, response_format
        return self.response


def test_cleanup_cli_requires_model_content_acknowledgement(tmp_path: Path) -> None:
    with pytest.raises(typer.BadParameter):
        clean_articles(
            db_path=tmp_path / "quality.db",
            dataset_version="v2.0",
            model="fake-model",
            event_linked_only=True,
            limit=1,
            force=False,
            allow_model_content=False,
        )


def _article(content: str) -> Article:
    return Article(
        id="article-1",
        title="A sufficiently long article title",
        content=content,
        url="https://example.com/article",
        source="Example",
        published_date=datetime(2025, 1, 2, tzinfo=timezone.utc),
        domain=Domain.GENERAL,
    )


def _event() -> Event:
    return Event(
        id="event-1",
        title="Council approves proposal",
        description="The city council approved the proposed policy on January 2.",
        event_type=EventType.DECISION,
        domain=Domain.GENERAL,
        occurred_date=datetime(2025, 1, 2, tzinfo=timezone.utc),
        status=EventStatus.OCCURRED,
        article_ids=["article-1"],
        source_article_id="article-1",
    )


def test_normalizer_unwraps_json_and_preserves_substantive_markdown() -> None:
    markdown = "# Headline\n\nThe council approved the proposal on January 2."
    content = json.dumps({"markdown": markdown, "status_code": 200})

    result = ArticleNormalizer().normalize(content)

    assert result.normalized_content == markdown
    assert ArticleQualityFlag.JSON_WRAPPER in result.flags
    assert result.metadata["wrapper_metadata"]["status_code"] == 200


@pytest.mark.asyncio
async def test_structured_client_unwraps_single_object_list() -> None:
    client = LiteLLMStructuredClient(
        FakeLiteLLMClient('[{"clean_markdown": "Article text"}]')
    )

    result = await client.complete_json("system", "user")

    assert result == {"clean_markdown": "Article text"}


def test_service_treats_successful_json_unwrap_as_complete(tmp_path: Path) -> None:
    markdown = "# Headline\n\n" + "Substantive article text. " * 10
    article = _article(json.dumps({"markdown": markdown}))
    db = GenericDatabase(str(tmp_path / "quality.db"))
    service = EvidenceQualityService(db, "v2.0")

    first = service.process_article(article)
    second = service.process_article(article)

    assert first.status.value == "complete"
    assert first.id == second.id
    assert len(db.get_many(ArticleQualityRecord)) == 1


def test_service_marks_later_exact_content_duplicate(tmp_path: Path) -> None:
    content = "Substantive article text about a public decision. " * 5
    first_article = _article(content)
    second_article = _article(content).model_copy(update={"id": "article-2"})
    db = GenericDatabase(str(tmp_path / "quality.db"))
    service = EvidenceQualityService(db, "v2.0")

    first = service.process_article(first_article)
    second = service.process_article(second_article)

    assert ArticleQualityFlag.EXACT_DUPLICATE not in first.flags
    assert ArticleQualityFlag.EXACT_DUPLICATE in second.flags
    assert second.metadata["duplicate_of_article_id"] == "article-1"


def test_normalizer_flags_page_quality_risks() -> None:
    content = (
        "Cookie consent and privacy choices\n\n"
        + "[navigation](https://example.com)\n" * 101
        + "<div>Article content truncated</div>"
    )

    result = ArticleNormalizer(max_chars=500).normalize(content)

    assert ArticleQualityFlag.CONSENT_LEADING in result.flags
    assert ArticleQualityFlag.LINK_HEAVY in result.flags
    assert ArticleQualityFlag.RAW_HTML in result.flags
    assert ArticleQualityFlag.TRUNCATED in result.flags
    assert ArticleQualityFlag.TOO_LONG in result.flags


def test_traceability_compares_visible_markdown_text() -> None:
    snapshot = (
        "[Microsoft (MSFT)](https://example.com/msft)-backed "
        "[OpenAI](https://example.com/openai) announced a model."
    )
    passage = "Microsoft (MSFT)-backed OpenAI announced a model."

    assert passage_is_traceable(passage, snapshot) is True


def test_cleaning_fidelity_ignores_markdown_formatting() -> None:
    source = (
        "The company reported strong growth in the quarter. "
        "[Revenue](https://example.com) increased by 20 percent."
    )
    cleaned = (
        "## Results\n\nThe company reported strong growth in the quarter. "
        "**Revenue** increased by 20 percent."
    )

    result = measure_cleaning_fidelity(source, cleaned)

    assert result["exact_visible_sentence_rate"] == 1.0


@pytest.mark.asyncio
async def test_grounding_requires_traceable_exact_passages(tmp_path: Path) -> None:
    content = (
        "The council approved the proposal on January 2 after a public vote. "
        "Officials published the result later that day."
    )
    article = _article(content)
    event = _event()
    extractor = EventEvidenceExtractor(
        FakeStructuredLLM(
            "extractor-model",
            [
                {
                    "supporting_passages": [
                        "The council approved the proposal on January 2"
                    ],
                    "contradicting_passages": [],
                    "date_passages": ["January 2"],
                    "proposed_claim": None,
                    "proposed_date": None,
                }
            ],
        )
    )
    verifier = EventEvidenceVerifier(
        FakeStructuredLLM(
            "independent-verifier",
            [
                {
                    "support": "full",
                    "date_validity": "correct",
                    "entity_match": "correct",
                    "action": "accept",
                    "confidence": 0.95,
                    "reason_codes": ["claim_and_date_supported"],
                    "notes": "Exact passage supports the event.",
                }
            ],
        )
    )
    db = GenericDatabase(str(tmp_path / "quality.db"))
    service = EvidenceQualityService(
        db,
        "v2.0",
        extractor=extractor,
        verifier=verifier,
    )

    extraction, verification = await service.validate_event(event, article)

    assert extraction.all_passages_traceable is True
    assert extraction.traceability_version == "markdown-visible-v2"
    assert verification.action == RepairAction.ACCEPT
    assert db.get(EventEvidenceExtraction, extraction.id) is not None
    assert db.get(EventEvidenceVerification, verification.id) is not None
    records = db.get_many(ArticleQualityRecord)
    assert len(records) == 1
    assert records[0].normalized_content == content
    repairs = db.get_many(DatasetRepairRecord)
    assert len(repairs) == 1
    assert repairs[0].action == RepairAction.ACCEPT
    assert repairs[0].applied is False


@pytest.mark.asyncio
async def test_verifier_is_not_called_for_untraceable_passage() -> None:
    article = _article(
        "The article contains no such statement but is long enough for storage. "
        "It discusses a separate public meeting and gives no decision outcome."
    )
    event = _event()
    extractor = EventEvidenceExtractor(
        FakeStructuredLLM(
            "extractor-model",
            [
                {
                    "supporting_passages": ["A fabricated verbatim passage"],
                    "contradicting_passages": [],
                    "date_passages": [],
                }
            ],
        )
    )
    verifier_llm = FakeStructuredLLM("verifier-model", [])
    extraction = await extractor.extract(
        event,
        article,
        input_content=article.content,
        traceability_snapshot=article.content,
        dataset_version="v2.0",
    )
    verification = await EventEvidenceVerifier(verifier_llm).verify(
        event, article, extraction
    )

    assert extraction.all_passages_traceable is False
    assert verification.action == RepairAction.DEFER_UNVERIFIABLE
    assert verification.model == "deterministic/traceability-gate"
    assert verifier_llm.responses == []


def test_version_service_preserves_question_ids(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    with __import__("sqlite3").connect(source) as conn:
        conn.execute("CREATE TABLE questions (id TEXT PRIMARY KEY)")
        conn.executemany("INSERT INTO questions VALUES (?)", [("q2",), ("q1",)])
    service = DatasetVersionService(tmp_path / "versions")

    v1 = service.create_release(source, "v1")
    v2 = service.create_release(
        tmp_path / "versions" / "v1" / "worldreasoner.db",
        "v2.0",
        parent_version="v1",
    )

    assert v1["counts"]["questions"] == 2
    assert v2["counts"]["questions"] == 2
    assert v1["question_id_sha256"] == v2["question_id_sha256"]

    refreshed = service.refresh_manifest(
        "v2.0",
        llm_passes=[{"pass": "smoke", "model": "fake-model", "records": 2}],
    )
    assert refreshed["llm_passes"][0]["model"] == "fake-model"
    assert refreshed["created_at"] == v2["created_at"]
    assert "updated_at" in refreshed


def test_version_service_rejects_path_traversal(tmp_path: Path) -> None:
    service = DatasetVersionService(tmp_path / "versions")

    with pytest.raises(ValueError):
        service.create_release(tmp_path / "source.db", "../outside")
