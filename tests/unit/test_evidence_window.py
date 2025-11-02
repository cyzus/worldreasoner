from datetime import datetime, timezone, timedelta
import pytest

from src.pipelines.stages.evidence_collection import EvidenceCollectionConfig, HindsightEvidenceCollectionStage
from src.domain.models.question import Question, QuestionType


def make_question(resolution_date: datetime) -> Question:
    return Question(
        id="q_test_001",
        question_text="Is this a test question that is long enough?",
        question_type=QuestionType.BOOLEAN,
        domain="test",
        difficulty=1,
        resolution_date=resolution_date,
        ground_truth=True,
    )


def test_explicit_start_and_end_used():
    config = EvidenceCollectionConfig(
        evidence_window_days=30,
        evidence_start_date=datetime(2025, 9, 1, tzinfo=timezone.utc),
        evidence_end_date=datetime(2025, 9, 10, tzinfo=timezone.utc),
    )
    stage = HindsightEvidenceCollectionStage(config=config)
    q = make_question(datetime(2025, 10, 1, tzinfo=timezone.utc))

    start, end = stage._compute_evidence_window(q)
    assert start == datetime(2025, 9, 1, tzinfo=timezone.utc)
    assert end == datetime(2025, 9, 10, tzinfo=timezone.utc)


def test_start_only_computes_end_and_caps_at_resolution_minus_one():
    config = EvidenceCollectionConfig(
        evidence_window_days=10,
        evidence_start_date=datetime(2025, 9, 25, tzinfo=timezone.utc),
        evidence_end_date=None,
    )
    stage = HindsightEvidenceCollectionStage(config=config)
    # resolution is 2025-09-30, resolution-1 = 2025-09-29
    q = make_question(datetime(2025, 9, 30, tzinfo=timezone.utc))

    start, end = stage._compute_evidence_window(q)
    assert start == datetime(2025, 9, 25, tzinfo=timezone.utc)
    # computed end would be 2025-10-04 but should be capped to resolution-1 (2025-09-29)
    assert end == datetime(2025, 9, 29, tzinfo=timezone.utc)


def test_default_anchor_to_resolution():
    config = EvidenceCollectionConfig(
        evidence_window_days=7,
    )
    stage = HindsightEvidenceCollectionStage(config=config)
    q = make_question(datetime(2025, 10, 8, tzinfo=timezone.utc))

    start, end = stage._compute_evidence_window(q)
    assert end == datetime(2025, 10, 7, tzinfo=timezone.utc)
    assert start == datetime(2025, 10, 1, tzinfo=timezone.utc)


def test_config_validator_rejects_end_before_start():
    with pytest.raises(ValueError):
        EvidenceCollectionConfig(
            evidence_window_days=5,
            evidence_start_date=datetime(2025, 9, 10, tzinfo=timezone.utc),
            evidence_end_date=datetime(2025, 9, 5, tzinfo=timezone.utc),
        )
