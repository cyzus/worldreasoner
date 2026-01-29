"""Unit tests for CausalHypothesis model."""

from datetime import datetime

import pytest

from src.domain.models import CausalHypothesis, CausalRelationType


def test_causal_hypothesis_creation():
    """Test basic causal hypothesis creation."""
    hypothesis = CausalHypothesis(
        id="hyp_test_001",
        discovered_by_question_ids=["q_test_001"],
        source_event_id="evt_cause_001",
        target_event_id="evt_effect_001",
        relation_type=CausalRelationType.CAUSES,
        strength=0.8,
        confidence=0.9,
        reasoning="Event A directly caused Event B through mechanism X",
        evidence_article_ids=["art_001", "art_002"],
    )

    assert hypothesis.id == "hyp_test_001"
    assert "q_test_001" in hypothesis.discovered_by_question_ids
    assert hypothesis.source_event_id == "evt_cause_001"
    assert hypothesis.target_event_id == "evt_effect_001"
    assert hypothesis.relation_type == CausalRelationType.CAUSES
    assert hypothesis.strength == 0.8
    assert hypothesis.confidence == 0.9
    assert len(hypothesis.evidence_article_ids) == 2


def test_causal_hypothesis_with_enables_relation():
    """Test hypothesis with ENABLES relation type."""
    hypothesis = CausalHypothesis(
        id="hyp_test_002",
        discovered_by_question_ids=["q_test_002"],
        source_event_id="evt_enable_001",
        target_event_id="evt_enabled_001",
        relation_type=CausalRelationType.ENABLES,
        strength=0.6,
        confidence=0.7,
        reasoning="Event A enabled Event B to occur",
        evidence_article_ids=["art_003"],
    )

    assert hypothesis.relation_type == CausalRelationType.ENABLES
    assert hypothesis.strength == 0.6
    assert hypothesis.confidence == 0.7


def test_meets_thresholds_pass():
    """Test that hypothesis meets quality thresholds."""
    hypothesis = CausalHypothesis(
        id="hyp_test_003",
        question_id="q_test_003",
        source_event_id="evt_001",
        target_event_id="evt_002",
        relation_type=CausalRelationType.CAUSES,
        strength=0.7,
        confidence=0.8,
        reasoning="Strong causal link with high confidence",
        evidence_article_ids=["art_004"],
    )

    assert hypothesis.meets_thresholds(min_confidence=0.6, min_strength=0.3)
    assert hypothesis.meets_thresholds(min_confidence=0.7, min_strength=0.5)
    assert hypothesis.meets_thresholds(min_confidence=0.8, min_strength=0.7)


def test_meets_thresholds_fail():
    """Test that hypothesis fails quality thresholds."""
    hypothesis = CausalHypothesis(
        id="hyp_test_004",
        question_id="q_test_004",
        source_event_id="evt_001",
        target_event_id="evt_002",
        relation_type=CausalRelationType.CORRELATES,
        strength=0.4,
        confidence=0.5,
        reasoning="Weak correlation",
        evidence_article_ids=["art_005"],
    )

    # Should fail - confidence too low
    assert not hypothesis.meets_thresholds(min_confidence=0.6, min_strength=0.3)

    # Should fail - strength too low
    assert not hypothesis.meets_thresholds(min_confidence=0.4, min_strength=0.5)

    # Should pass
    assert hypothesis.meets_thresholds(min_confidence=0.5, min_strength=0.4)


def test_has_evidence_with_citations():
    """Test has_evidence returns True when evidence is cited."""
    hypothesis = CausalHypothesis(
        id="hyp_test_005",
        question_id="q_test_005",
        source_event_id="evt_001",
        target_event_id="evt_002",
        relation_type=CausalRelationType.CAUSES,
        strength=0.7,
        confidence=0.8,
        reasoning="Well-documented causal link",
        evidence_article_ids=["art_006", "art_007", "art_008"],
    )

    assert hypothesis.has_evidence()
    assert len(hypothesis.evidence_article_ids) == 3


def test_has_evidence_without_citations():
    """Test has_evidence returns False when no evidence is cited."""
    hypothesis = CausalHypothesis(
        id="hyp_test_006",
        question_id="q_test_006",
        source_event_id="evt_001",
        target_event_id="evt_002",
        relation_type=CausalRelationType.CAUSES,
        strength=0.7,
        confidence=0.8,
        reasoning="Causal link without citations",
        evidence_article_ids=[],
    )

    assert not hypothesis.has_evidence()


def test_add_discovery():
    """Test adding a discovery to a hypothesis."""
    hypothesis = CausalHypothesis(
        id="hyp_test_007",
        discovered_by_question_ids=["q_test_007"],
        source_event_id="evt_001",
        target_event_id="evt_002",
        relation_type=CausalRelationType.CAUSES,
        strength=0.8,
        confidence=0.9,
        reasoning="Validated causal link",
        evidence_article_ids=["art_009"],
    )

    assert "q_test_007" in hypothesis.discovered_by_question_ids
    assert len(hypothesis.discovered_by_question_ids) == 1

    hypothesis.add_discovery("q_test_008")

    assert "q_test_008" in hypothesis.discovered_by_question_ids
    assert len(hypothesis.discovered_by_question_ids) == 2


def test_default_metadata_fields():
    """Test that metadata fields have correct defaults."""
    hypothesis = CausalHypothesis(
        id="hyp_test_008",
        discovered_by_question_ids=["q_test_008"],
        source_event_id="evt_001",
        target_event_id="evt_002",
        relation_type=CausalRelationType.CAUSES,
        strength=0.7,
        confidence=0.8,
        reasoning="Test hypothesis",
        evidence_article_ids=["art_010"],
    )

    assert hypothesis.identified_by == "evidence_pipeline"
    assert isinstance(hypothesis.first_identified_at, datetime)


def test_prevents_relation_type():
    """Test hypothesis with PREVENTS relation type."""
    hypothesis = CausalHypothesis(
        id="hyp_test_009",
        question_id="q_test_009",
        source_event_id="evt_prevent_001",
        target_event_id="evt_prevented_001",
        relation_type=CausalRelationType.PREVENTS,
        strength=0.9,
        confidence=0.85,
        reasoning="Event A prevented Event B from occurring",
        evidence_article_ids=["art_011"],
    )

    assert hypothesis.relation_type == CausalRelationType.PREVENTS
    assert hypothesis.strength == 0.9


def test_conditional_relation_type():
    """Test hypothesis with CONDITIONAL relation type."""
    hypothesis = CausalHypothesis(
        id="hyp_test_010",
        question_id="q_test_010",
        source_event_id="evt_cond_001",
        target_event_id="evt_result_001",
        relation_type=CausalRelationType.CONDITIONAL,
        strength=0.75,
        confidence=0.7,
        reasoning="Event A causes Event B only under certain conditions",
        evidence_article_ids=["art_012"],
    )

    assert hypothesis.relation_type == CausalRelationType.CONDITIONAL


def test_reasoning_minimum_length():
    """Test that reasoning has minimum length requirement."""
    # This should work (>= 10 chars)
    hypothesis = CausalHypothesis(
        id="hyp_test_011",
        question_id="q_test_011",
        source_event_id="evt_001",
        target_event_id="evt_002",
        relation_type=CausalRelationType.CAUSES,
        strength=0.7,
        confidence=0.8,
        reasoning="Valid reason",
        evidence_article_ids=["art_013"],
    )

    assert len(hypothesis.reasoning) >= 10


def test_strength_and_confidence_bounds():
    """Test that strength and confidence are within [0, 1] bounds."""
    hypothesis = CausalHypothesis(
        id="hyp_test_012",
        question_id="q_test_012",
        source_event_id="evt_001",
        target_event_id="evt_002",
        relation_type=CausalRelationType.CAUSES,
        strength=0.0,  # Min value
        confidence=1.0,  # Max value
        reasoning="Testing boundary values",
        evidence_article_ids=["art_014"],
    )

    assert hypothesis.strength == 0.0
    assert hypothesis.confidence == 1.0


def test_invalid_strength_fails():
    """Test that invalid strength value is rejected."""
    with pytest.raises(Exception):  # Pydantic validation error
        CausalHypothesis(
            id="hyp_test_013",
            question_id="q_test_013",
            source_event_id="evt_001",
            target_event_id="evt_002",
            relation_type=CausalRelationType.CAUSES,
            strength=1.5,  # Invalid: > 1.0
            confidence=0.8,
            reasoning="Invalid strength",
            evidence_article_ids=["art_015"],
        )


def test_invalid_confidence_fails():
    """Test that invalid confidence value is rejected."""
    with pytest.raises(Exception):  # Pydantic validation error
        CausalHypothesis(
            id="hyp_test_014",
            question_id="q_test_014",
            source_event_id="evt_001",
            target_event_id="evt_002",
            relation_type=CausalRelationType.CAUSES,
            strength=0.7,
            confidence=-0.1,  # Invalid: < 0.0
            reasoning="Invalid confidence",
            evidence_article_ids=["art_016"],
        )
