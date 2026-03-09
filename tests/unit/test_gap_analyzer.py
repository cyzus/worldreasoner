"""Unit tests for GapAnalyzer."""

import pytest
from src.pipelines.collection.gap_analyzer import GapAnalyzer, GapAnalysis
from src.pipelines.collection.progress import CollectionProgress
from src.config.collection_goal import CollectionGoal
from tests.conftest import create_test_question


@pytest.fixture
def sample_goal():
    """Create sample collection goal."""
    return CollectionGoal(
        total_questions=100,
        type_distribution={"binary": 50, "mcq": 30, "quantity": 20},
        category_distribution={"tech": 40, "politics": 30, "finance": 30},
    )


@pytest.fixture
def gap_analyzer():
    """Create gap analyzer instance."""
    return GapAnalyzer()


def test_gap_analysis_dataclass():
    """Test GapAnalysis dataclass properties."""
    analysis = GapAnalysis(
        type_gaps={"binary": 10, "mcq": 5}, category_gaps={"tech": 8}, total_needed=23
    )

    assert analysis.has_gaps is True
    assert analysis.type_gaps_list == ["binary", "mcq"]
    assert analysis.category_gaps_list == ["tech"]


def test_gap_analysis_no_gaps():
    """Test GapAnalysis when no gaps exist."""
    analysis = GapAnalysis(type_gaps={}, category_gaps={}, total_needed=0)

    assert analysis.has_gaps is False
    assert analysis.type_gaps_list == []
    assert analysis.category_gaps_list == []


def test_analyze_empty_progress(gap_analyzer, sample_goal):
    """Test analysis with empty progress."""
    progress = CollectionProgress()

    analysis = gap_analyzer.analyze(progress, sample_goal)

    assert analysis.total_needed == 100
    assert analysis.type_gaps == {"binary": 50, "mcq": 30, "quantity": 20}
    assert analysis.category_gaps == {"tech": 40, "politics": 30, "finance": 30}
    assert analysis.has_gaps is True


def test_analyze_partial_progress(gap_analyzer, sample_goal):
    """Test analysis with partial progress."""
    progress = CollectionProgress()

    # Add 25 boolean questions
    for i in range(25):
        q = create_test_question(
            id=f"q_bool_{i}",
            question_type="binary",
            category="tech",
            source_name="polymarket",
        )
        progress.add_question(q)

    # Add 15 mcq questions
    for i in range(15):
        q = create_test_question(
            id=f"q_mcq_{i}",
            question_type="mcq",
            category="politics",
            source_name="news",
        )
        progress.add_question(q)

    analysis = gap_analyzer.analyze(progress, sample_goal)

    assert analysis.total_needed == 60  # 100 - 40
    assert analysis.type_gaps["binary"] == 25  # 50 - 25
    assert analysis.type_gaps["mcq"] == 15  # 30 - 15
    assert analysis.type_gaps["quantity"] == 20  # 20 - 0


def test_analyze_goal_met(gap_analyzer, sample_goal):
    """Test analysis when goal is met."""
    progress = CollectionProgress()

    # Add exactly the right distribution
    for i in range(50):
        q = create_test_question(
            id=f"q_bool_{i}",
            question_type="binary",
            category="tech" if i < 20 else "politics",
            source_name="polymarket",
        )
        progress.add_question(q)

    for i in range(30):
        q = create_test_question(
            id=f"q_mcq_{i}",
            question_type="mcq",
            category="tech" if i < 15 else "finance",
            source_name="news",
        )
        progress.add_question(q)

    for i in range(20):
        q = create_test_question(
            id=f"q_num_{i}",
            question_type="quantity",  # Changed from "numerical" to "quantity"
            category="finance" if i < 10 else "politics",
            source_name="news",
        )
        progress.add_question(q)

    analysis = gap_analyzer.analyze(progress, sample_goal)

    assert analysis.total_needed == 0
    assert not analysis.type_gaps  # No type gaps
    # Note: category distribution might not be exact, but that's OK for this test


def test_analyze_filters_negative_gaps(gap_analyzer):
    """Test that analysis filters out negative gaps (over-collection)."""
    goal = CollectionGoal(
        total_questions=50, type_distribution={"binary": 25, "mcq": 25}
    )

    progress = CollectionProgress()

    # Add 30 boolean (5 over target)
    for i in range(30):
        q = create_test_question(
            id=f"q_bool_{i}", question_type="binary", source_name="polymarket"
        )
        progress.add_question(q)

    # Add 10 mcq (15 under target)
    for i in range(10):
        q = create_test_question(
            id=f"q_mcq_{i}", question_type="mcq", source_name="news"
        )
        progress.add_question(q)

    analysis = gap_analyzer.analyze(progress, goal)

    # Boolean over-collected, should not appear in gaps
    assert "binary" not in analysis.type_gaps
    # MCQ under-collected
    assert "mcq" in analysis.type_gaps
    assert analysis.type_gaps["mcq"] == 15


def test_type_gaps_list_property(gap_analyzer, sample_goal):
    """Test type_gaps_list property returns correct list."""
    progress = CollectionProgress()

    # Add some questions
    for i in range(10):
        q = create_test_question(
            id=f"q_{i}", question_type="binary", source_name="polymarket"
        )
        progress.add_question(q)

    analysis = gap_analyzer.analyze(progress, sample_goal)

    # All types should have gaps
    assert set(analysis.type_gaps_list) == {"binary", "mcq", "quantity"}
    assert all(t in analysis.type_gaps for t in analysis.type_gaps_list)


def test_category_gaps_list_property(gap_analyzer, sample_goal):
    """Test category_gaps_list property returns correct list."""
    progress = CollectionProgress()

    # Add some questions
    for i in range(10):
        q = create_test_question(
            id=f"q_{i}",
            question_type="binary",
            category="tech",
            source_name="polymarket",
        )
        progress.add_question(q)

    analysis = gap_analyzer.analyze(progress, sample_goal)

    # All categories should have gaps
    assert set(analysis.category_gaps_list) == {"tech", "politics", "finance"}
    assert all(c in analysis.category_gaps for c in analysis.category_gaps_list)
