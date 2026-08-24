"""Tests for deterministic construction migration-fixture analysis."""

from dataclasses import replace

from src.analysis.construction_fixture import (
    QuestionProfile,
    _graph_measurements,
    build_targets,
    select_fixture,
    selection_counts,
    stable_ids_hash,
)


def make_profile(index: int) -> QuestionProfile:
    return QuestionProfile(
        question_id=f"q{index:02d}",
        question_text=f"Will fixture event {index} occur before its deadline?",
        source="news" if index % 2 == 0 else "polymarket",
        question_type="binary" if index < 6 else "mcq",
        domain="politics" if index % 2 == 0 else "science",
        difficulty=2 if index < 4 else 3,
        resolution_date="2026-01-01T00:00:00+00:00",
        horizon_days=float(index + 1),
        article_count=index + 10,
        source_count=index + 1,
        event_count=10,
        outcome_count=2,
        edge_count=9,
        impact_count=10,
        unsupported_event_count=0,
        disconnected_event_count=0,
        graph_depth=4,
        graph_has_cycle=False,
        evidence_tier="q1" if index < 4 else "q2",
        horizon_tier="q1" if index % 2 == 0 else "q2",
    )


def test_graph_measurements_include_outcome_impact_path() -> None:
    depth, has_cycle, disconnected = _graph_measurements(
        {"e1", "e2"},
        {"o1"},
        [("e1", "e2"), ("e2", "o1")],
    )

    assert depth == 3
    assert has_cycle is False
    assert disconnected == 0


def test_graph_measurements_detect_cycle_and_disconnection() -> None:
    depth, has_cycle, disconnected = _graph_measurements(
        {"e1", "e2", "e3"},
        {"o1"},
        [("e1", "e2"), ("e2", "e1"), ("e3", "o1")],
    )

    assert depth == 2
    assert has_cycle is True
    assert disconnected == 2


def test_fixture_selection_is_deterministic_and_matches_targets() -> None:
    profiles = [make_profile(index) for index in range(8)]

    first, targets, first_score = select_fixture(
        profiles,
        size=4,
        seed="fixture-test",
        starts=4,
    )
    second, _, second_score = select_fixture(
        list(reversed(profiles)),
        size=4,
        seed="fixture-test",
        starts=4,
    )

    assert [item.question_id for item in first] == [
        item.question_id for item in second
    ]
    assert first_score == second_score == 0.0
    assert selection_counts(first) == targets


def test_targets_retain_rare_categories() -> None:
    profiles = [make_profile(index) for index in range(8)]
    profiles[-1] = replace(profiles[-1], question_type="timeframe")

    targets = build_targets(profiles, size=4)

    assert targets["question_type"]["timeframe"] == 1
    assert sum(targets["question_type"].values()) == 4


def test_stable_ids_hash_ignores_input_order_and_duplicates() -> None:
    assert stable_ids_hash(["q2", "q1", "q1"]) == stable_ids_hash(["q1", "q2"])
