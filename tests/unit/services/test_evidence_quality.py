"""Tests for the modular v2 evidence-quality passes."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest
import typer

from src.cli.commands.dataset import clean_articles
from src.core.database import GenericDatabase
from src.core.llm import LiteLLMClient
from src.domain.models import (
    Article,
    ArticleQualityFlag,
    ArticleQualityRecord,
    DateLabel,
    DatasetRepairRecord,
    Domain,
    Event,
    EventEvidenceExtraction,
    EventEvidenceVerification,
    EventStatus,
    EventType,
    QualityStatus,
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
from src.services.evidence_quality.article_cleaner import (
    ArticleMarkdownCleaner,
    measure_cleaning_fidelity,
)
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
        response_model=None,
    ) -> Dict[str, Any]:
        del system_prompt, user_prompt, response_model
        return self.responses.pop(0)


class FakeLiteLLMClient:
    """Minimal LiteLLM client stub for response-shape compatibility tests."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.llm_config = {"model": "fake-model"}

    async def acomplete(self, messages, response_format=None) -> str:
        del messages, response_format
        return self.response


class FakeModelResponse(dict):
    """Dictionary response carrying LiteLLM-style hidden cost metadata."""

    def __init__(self, *args, response_cost: float, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._hidden_params = {"response_cost": response_cost}


def test_cleanup_cli_requires_model_content_acknowledgement(tmp_path: Path) -> None:
    with pytest.raises(typer.BadParameter):
        clean_articles(
            db_path=tmp_path / "quality.db",
            dataset_version="v2.0",
            model="fake-model",
            timeout=300,
            concurrency=3,
            event_linked_only=True,
            limit=1,
            force=False,
            selection_file=None,
            usage_report=None,
            allow_model_content=False,
        )


def test_litellm_client_records_tokens_and_response_cost() -> None:
    client = LiteLLMClient({"model": "fake-model"})
    response = FakeModelResponse(
        {
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 30,
                "total_tokens": 150,
            }
        },
        response_cost=0.0125,
    )

    client._record_usage(response, litellm_module=None)
    report = client.get_usage_report()

    assert report["calls"] == 1
    assert report["prompt_tokens"] == 120
    assert report["completion_tokens"] == 30
    assert report["total_tokens"] == 150
    assert report["estimated_cost_usd"] == 0.0125


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


def test_question_readiness_requires_cleanup_for_every_eligible_article(
    tmp_path: Path,
) -> None:
    article = _article("Substantive article text about a public decision. " * 10)
    article.collected_for_question_id = "question-1"
    db = GenericDatabase(str(tmp_path / "quality.db"))
    db.create_table(Article)
    db.save(Article, article)
    service = EvidenceQualityService(db, "v2.0")

    service.process_article(article)
    pending = service.question_readiness("question-1")

    assert pending.is_quality_managed is True
    assert pending.is_ready is False
    assert pending.pending_cleanup_articles == 1

    record = service.get_article_record(article.id)
    record.clean_markdown = "# Article\n\nSubstantive article text."
    record.cleaner_model = "cleaner-model"
    record.status = QualityStatus.COMPLETE
    db.save(ArticleQualityRecord, record)

    ready = service.question_readiness("question-1")

    assert ready.is_ready is True
    assert ready.cleaned_articles == 1
    assert ready.pending_cleanup_articles == 0


def test_question_readiness_does_not_send_deterministically_blocked_article(
    tmp_path: Path,
) -> None:
    article = _article(
        "# Whoops!\n\nSomething went wrong. 404 page not found. "
        + "This generic page does not contain the requested article. " * 3
    )
    article.collected_for_question_id = "question-1"
    db = GenericDatabase(str(tmp_path / "quality.db"))
    db.create_table(Article)
    db.save(Article, article)
    service = EvidenceQualityService(db, "v2.0")

    service.process_article(article)
    readiness = service.question_readiness("question-1")

    assert readiness.blocked_articles == 1
    assert readiness.pending_cleanup_articles == 0
    assert readiness.is_ready is False


def test_normalization_rerun_preserves_cleaned_markdown(tmp_path: Path) -> None:
    article = _article("Substantive article text. " * 10)
    db = GenericDatabase(str(tmp_path / "quality.db"))
    service = EvidenceQualityService(db, "v2.0")
    record = service.process_article(article)
    record.clean_markdown = "# Article\n\nSubstantive article text."
    record.cleaner_model = "cleaner-model"
    record.cleaner_prompt_version = "cleaner-v1"
    record.metadata["cleaner_fidelity"] = {"exact_visible_sentence_rate": 1.0}
    db.save(ArticleQualityRecord, record)

    rerun = service.process_article(article)

    assert rerun.clean_markdown == record.clean_markdown
    assert rerun.cleaner_model == "cleaner-model"
    assert rerun.cleaner_prompt_version == "cleaner-v1"
    assert rerun.metadata["cleaner_fidelity"] == {
        "exact_visible_sentence_rate": 1.0
    }


def test_ensure_article_record_refreshes_stale_normalizer(tmp_path: Path) -> None:
    article = _article(
        "# Whoops!\n\nSomething went wrong. 404 page not found. "
        + "This generic page does not contain the requested article. " * 3
    )
    db = GenericDatabase(str(tmp_path / "quality.db"))
    service = EvidenceQualityService(db, "v2.0")
    stale = service.process_article(article)
    stale.normalizer_version = "article-normalizer-v1"
    stale.flags = []
    db.save(ArticleQualityRecord, stale)

    refreshed = service.ensure_article_record(article)

    assert refreshed.normalizer_version == "article-normalizer-v5"
    assert ArticleQualityFlag.ERROR_PAGE in refreshed.flags
    assert service.article_is_eligible_for_llm(refreshed) is False


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


def test_normalizer_blocks_error_page_before_llm_cleanup() -> None:
    content = "# Whoops!\n\nSomething went wrong.\n\n404 page not found."

    result = ArticleNormalizer().normalize(
        content,
        expected_title="Instacart users report billing errors and overcharges",
    )

    assert ArticleQualityFlag.ERROR_PAGE in result.flags
    assert result.metadata["identity_check"]["eligible"] is False


def test_normalizer_blocks_explicit_access_challenge() -> None:
    content = (
        "# Bloomberg\n\nWe've detected unusual activity from your computer "
        "network. Please click the box below to let us know you're not a robot."
    )

    result = ArticleNormalizer().normalize(
        content,
        expected_title="Google Gemini model release scheduled for December",
    )

    assert ArticleQualityFlag.ACCESS_BLOCK in result.flags
    assert result.metadata["identity_check"]["eligible"] is False


def test_truncated_snapshot_remains_in_conservative_repair_path(
    tmp_path: Path,
) -> None:
    content = (
        "# A sufficiently long article title\n\n"
        + "Substantive article reporting with dates and named entities. " * 10
        + "\n\n[Content truncated at 50,000 characters]"
    )
    db = GenericDatabase(str(tmp_path / "quality.db"))
    service = EvidenceQualityService(db, "v2.0")

    record = service.process_article(_article(content))

    assert ArticleQualityFlag.TRUNCATED in record.flags
    assert service.article_is_eligible_for_llm(record) is False


def test_normalizer_blocks_unrelated_link_listing() -> None:
    content = "\n".join(
        f"[Unrelated headline {index}](https://example.com/{index})"
        for index in range(12)
    )

    result = ArticleNormalizer().normalize(
        content,
        expected_title="Uganda projects double digit growth from oil production",
    )

    assert ArticleQualityFlag.LIKELY_WRONG_PAGE in result.flags
    identity = result.metadata["identity_check"]
    assert identity["title_token_coverage"] == 0.0
    assert identity["eligible"] is False


def test_normalizer_blocks_msn_consent_shell() -> None:
    content = (
        "; ;\nContinue reading\n"
        "## More for You\n"
        "## More for You\n"
        "## Microsoft Cares About Your Privacy\n\n"
        "Microsoft and our partners use cookies to personalize content."
    )

    result = ArticleNormalizer().normalize(
        content,
        expected_title="Tanker arrives at Golden Pass LNG terminal",
    )

    identity = result.metadata["identity_check"]
    assert identity["consent_shell_detected"] is True
    assert "consent_shell_without_article_body" in identity["reasons"]
    assert ArticleQualityFlag.LIKELY_WRONG_PAGE in result.flags


def test_normalizer_blocks_generic_msn_privacy_shell() -> None:
    content = (
        "## Microsoft Cares About Your Privacy\n\n"
        "Microsoft and our third-party vendors use cookies to store and access "
        "information. Number of Partners (vendors): 960. List of Partners. "
        "I Accept Reject All Manage Preferences."
    )

    result = ArticleNormalizer().normalize(
        content,
        expected_title="EU aims to ease energy blow from Iran war",
    )

    identity = result.metadata["identity_check"]
    assert identity["consent_shell_detected"] is True
    assert identity["eligible"] is False


def test_normalizer_blocks_failed_site_and_captcha_page() -> None:
    content = (
        "A required part of this site couldn’t load. This may be due to a "
        "browser extension or network issues. Incorrect CAPTCHA. Submit."
    )

    result = ArticleNormalizer().normalize(
        content,
        expected_title="AAMC comments on organ transplant model",
    )

    assert ArticleQualityFlag.ACCESS_BLOCK in result.flags
    assert result.metadata["identity_check"]["eligible"] is False


def test_normalizer_blocks_cookie_settings_shell() -> None:
    content = (
        "This website uses cookies. [#GPC_BANNER_ICON#] [#GPC_TOAST_TEXT#] "
        "Consent Selection. Necessary Preferences "
        "Statistics Marketing. "
        + "Cookie provider and retention details. " * 20
        + "Cookie List. Reject All Confirm My Choices."
    )

    result = ArticleNormalizer().normalize(
        content,
        expected_title="Novartis and Viatris face Henrietta Lacks lawsuits",
    )

    identity = result.metadata["identity_check"]
    assert identity["cookie_settings_shell_detected"] is True
    assert identity["eligible"] is False


def test_normalizer_blocks_cnbc_navigation_shell_without_heading() -> None:
    links = "\n".join(
        f"[Navigation {index}](https://www.cnbc.com/{index})"
        for index in range(100)
    )
    content = (
        f"{links}\n\n"
        "Data is a real-time snapshot *Data is delayed at least 15 minutes. "
        "Global Business and Financial News, Stock Quotes, and Market Data "
        "and Analysis."
    )

    result = ArticleNormalizer().normalize(
        content,
        expected_title="Instacart in settlement talks with FTC",
    )

    identity = result.metadata["identity_check"]
    assert identity["navigation_shell_detected"] is True
    assert "navigation_shell_without_article_body" in identity["reasons"]
    assert ArticleQualityFlag.LIKELY_WRONG_PAGE in result.flags


def test_normalizer_keeps_cnbc_article_with_heading_and_body() -> None:
    links = "\n".join(
        f"[Navigation {index}](https://www.cnbc.com/{index})"
        for index in range(100)
    )
    content = (
        f"{links}\n\n"
        "# Instacart in settlement talks with FTC\n\n"
        "The company entered settlement talks after a regulatory inquiry.\n\n"
        "Data is a real-time snapshot *Data is delayed at least 15 minutes. "
        "Global Business and Financial News, Stock Quotes, and Market Data "
        "and Analysis."
    )

    result = ArticleNormalizer().normalize(
        content,
        expected_title="Instacart in settlement talks with FTC",
    )

    identity = result.metadata["identity_check"]
    assert identity["navigation_shell_detected"] is False
    assert identity["eligible"] is True


def test_traceability_compares_visible_markdown_text() -> None:
    snapshot = (
        "[Microsoft (MSFT)](https://example.com/msft)-backed "
        "[OpenAI](https://example.com/openai) announced a model."
    )
    passage = "Microsoft (MSFT)-backed OpenAI announced a model."

    assert passage_is_traceable(passage, snapshot) is True


def test_traceability_does_not_treat_less_than_comparison_as_html() -> None:
    snapshot = (
        "The difference was significant (_P_ < 0.001). In summary, our study "
        "indicates that early treatment substantially improves PFS and OS. "
        "Registration: <span>NCT05549037</span>."
    )
    passage = (
        "In summary, our study indicates that early treatment substantially "
        "improves PFS and OS."
    )

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
async def test_empty_cleanup_is_recorded_as_completed_attempt(
    tmp_path: Path,
) -> None:
    article = _article("Navigation and page furniture only. " * 10)
    cleaner = ArticleMarkdownCleaner(
        FakeStructuredLLM(
            "cleaner-model",
            [
                {
                    "article_validity": "invalid",
                    "validity_reason": "Only navigation is present.",
                    "clean_markdown": "",
                }
            ],
        )
    )
    db = GenericDatabase(str(tmp_path / "quality.db"))
    service = EvidenceQualityService(db, "v2.0", cleaner=cleaner)

    record = await service.clean_article(article)

    assert record.clean_markdown == ""
    assert record.cleaner_model == "cleaner-model"
    assert record.status == QualityStatus.NEEDS_REPAIR
    assert record.metadata["cleaner_validity"]["article_validity"] == "invalid"
    assert service.article_is_eligible_for_llm(record) is False


@pytest.mark.asyncio
async def test_cleanup_normalizes_null_text_fields() -> None:
    cleaner = ArticleMarkdownCleaner(
        FakeStructuredLLM(
            "cleaner-model",
            [
                {
                    "article_validity": "invalid",
                    "validity_reason": None,
                    "clean_markdown": None,
                }
            ],
        )
    )

    result = await cleaner.clean("Navigation and page furniture only.")

    assert result.article_validity.value == "invalid"
    assert result.validity_reasons == []
    assert result.clean_markdown == ""


def test_terminal_cleanup_failure_is_persisted(tmp_path: Path) -> None:
    article = _article("Substantive article text. " * 10)
    cleaner = ArticleMarkdownCleaner(FakeStructuredLLM("cleaner-model", []))
    db = GenericDatabase(str(tmp_path / "quality.db"))
    service = EvidenceQualityService(db, "v2.0", cleaner=cleaner)

    record = service.record_terminal_cleanup_failure(
        article,
        RuntimeError("LLM returned no usable content after 3 retries."),
    )

    assert record.cleaner_model == "cleaner-model"
    assert record.clean_markdown is None
    assert record.status == QualityStatus.NEEDS_REPAIR
    assert record.metadata["cleaner_failure"]["terminal"] is True
    assert service.article_is_eligible_for_cleanup(record) is False


@pytest.mark.asyncio
async def test_valid_cleanup_is_recorded_and_remains_llm_eligible(
    tmp_path: Path,
) -> None:
    content = "The council approved the proposal after a public vote. " * 5
    article = _article(content)
    cleaner = ArticleMarkdownCleaner(
        FakeStructuredLLM(
            "cleaner-model",
            [
                {
                    "article_validity": "valid",
                    "validity_reason": "The target article body is present.",
                    "clean_markdown": content,
                }
            ],
        )
    )
    db = GenericDatabase(str(tmp_path / "quality.db"))
    service = EvidenceQualityService(db, "v2.0", cleaner=cleaner)

    record = await service.clean_article(article)

    assert record.status == QualityStatus.COMPLETE
    assert record.metadata["cleaner_validity"]["article_validity"] == "valid"
    assert service.article_is_eligible_for_llm(record) is True


@pytest.mark.asyncio
async def test_cleanup_accepts_article_body_after_invalid_furniture_chunk() -> None:
    cleaner = ArticleMarkdownCleaner(
        FakeStructuredLLM(
            "cleaner-model",
            [
                {
                    "article_validity": "invalid",
                    "validity_reason": "Navigation only.",
                    "clean_markdown": "",
                },
                {
                    "article_validity": "valid",
                    "validity_reason": "Target article body is present.",
                    "clean_markdown": "The council approved the proposal.",
                },
            ],
        ),
        chunk_chars=40,
    )

    result = await cleaner.clean(
        "Navigation links and cookie controls.\n\n"
        "The council approved the proposal.",
        expected_title="Council approves proposal",
    )

    assert result.article_validity.value == "valid"
    assert result.clean_markdown == "The council approved the proposal."


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
async def test_verifier_accepts_near_match_date_label() -> None:
    article = _article(
        "The council approved the proposal on January 3 after a public vote. "
        "Officials published the result later that day."
    )
    event = _event()
    extraction = EventEvidenceExtraction(
        event_id=event.id,
        article_id=article.id,
        dataset_version="v2.0",
        supporting_passages=["The council approved the proposal on January 3"],
        date_passages=["on January 3"],
        all_passages_traceable=True,
        model="extractor-model",
        prompt_version="event-evidence-extractor-v1",
    )
    verifier = EventEvidenceVerifier(
        FakeStructuredLLM(
            "independent-verifier",
            [
                {
                    "support": "full",
                    "date_validity": "near_match",
                    "entity_match": "correct",
                    "action": "revise",
                    "confidence": 0.9,
                    "reason_codes": ["same_event_within_two_days"],
                    "notes": "The article establishes the event one day later.",
                }
            ],
        )
    )

    verification = await verifier.verify(event, article, extraction)

    assert verification.date_validity == DateLabel.NEAR_MATCH
    assert verification.prompt_version == "event-evidence-verifier-v2"


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
    assert verification.reason_codes == ["untraceable_extracted_passage"]
    assert verifier_llm.responses == []


@pytest.mark.asyncio
async def test_empty_extraction_is_distinct_from_untraceable_passage() -> None:
    article = _article(
        "The article discusses a separate public meeting and provides no "
        "evidence for the event under review. " * 3
    )
    event = _event()
    extractor = EventEvidenceExtractor(
        FakeStructuredLLM(
            "extractor-model",
            [
                {
                    "supporting_passages": [],
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

    assert verification.reason_codes == ["no_evidence_extracted"]
    assert verification.notes == (
        "Pass A returned no supporting, contradicting, or date passages."
    )
    assert verifier_llm.responses == []


@pytest.mark.asyncio
async def test_invalid_snapshot_never_reaches_event_llms(tmp_path: Path) -> None:
    article = _article(
        "# Whoops!\n\nSomething went wrong. 404 page not found. "
        + "This generic navigation page does not contain the requested article. " * 3
    )
    event = _event()
    extractor_llm = FakeStructuredLLM("extractor-model", [])
    verifier_llm = FakeStructuredLLM("verifier-model", [])
    db = GenericDatabase(str(tmp_path / "quality.db"))
    service = EvidenceQualityService(
        db,
        "v2.0",
        extractor=EventEvidenceExtractor(extractor_llm),
        verifier=EventEvidenceVerifier(verifier_llm),
    )

    with pytest.raises(ValueError, match="ineligible for event validation"):
        await service.validate_event(event, article)

    assert extractor_llm.responses == []
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
