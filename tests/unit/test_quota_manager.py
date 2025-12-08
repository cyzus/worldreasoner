"""Unit tests for QuotaManager."""

import pytest
from src.pipelines.question.quota_manager import QuotaManager
from src.pipelines.question.progress import CollectionProgress
from src.config.collection_goal import CollectionGoal
from tests.conftest import create_test_question


@pytest.fixture
def sample_goal():
    """Create sample collection goal."""
    return CollectionGoal(
        total_questions=100,
        type_distribution={"boolean": 50, "mcq": 30, "numerical": 20},
        category_distribution={"tech": 40, "politics": 30, "economics": 30},
        source_quotas={"polymarket": 50, "news": 50}
    )


@pytest.fixture
def quota_manager(sample_goal):
    """Create quota manager instance."""
    return QuotaManager(sample_goal)


def test_quota_manager_initialization(quota_manager, sample_goal):
    """Test quota manager initializes correctly."""
    assert quota_manager.goal == sample_goal


def test_calculate_needed_empty_progress(quota_manager):
    """Test calculation with empty progress."""
    progress = CollectionProgress()
    
    # Should return min of: source_quota (50), overall (100), type_gap (100)
    needed = quota_manager.calculate_needed_from_source("polymarket", progress)
    assert needed == 50  # Limited by source quota


def test_calculate_needed_partial_progress(quota_manager):
    """Test calculation with partial progress."""
    progress = CollectionProgress()
    
    # Add 30 questions from polymarket
    for i in range(30):
        q = create_test_question(
            id=f"q_{i}",
            source_name="polymarket"
        )
        progress.add_question(q)
    
    # Should return min of: source_quota (20), overall (70), type_gap (70)
    needed = quota_manager.calculate_needed_from_source("polymarket", progress)
    assert needed == 20  # Limited by source quota (50 - 30 = 20)


def test_calculate_needed_quota_exceeded(quota_manager):
    """Test calculation when source quota is exceeded."""
    progress = CollectionProgress()
    
    # Add 60 questions from polymarket (exceeds quota of 50)
    for i in range(60):
        q = create_test_question(
            id=f"q_{i}",
            source_name="polymarket"
        )
        progress.add_question(q)
    
    needed = quota_manager.calculate_needed_from_source("polymarket", progress)
    assert needed == 0  # Quota exceeded


def test_calculate_needed_overall_goal_met(quota_manager):
    """Test calculation when overall goal is met."""
    progress = CollectionProgress()
    
    # Add 100 questions (goal met)
    for i in range(100):
        source = "polymarket" if i < 50 else "news"
        q = create_test_question(
            id=f"q_{i}",
            source_name=source
        )
        progress.add_question(q)
    
    needed = quota_manager.calculate_needed_from_source("polymarket", progress)
    assert needed == 0  # Overall goal met


def test_calculate_needed_unknown_source(quota_manager):
    """Test calculation for source without explicit quota."""
    progress = CollectionProgress()
    
    # Unknown source should default to 100
    needed = quota_manager.calculate_needed_from_source("unknown_source", progress)
    assert needed == 100  # Min of: default_quota (100), overall (100), type_gap (100)


def test_has_quota_available_true(quota_manager):
    """Test quota availability check when quota is available."""
    progress = CollectionProgress()
    
    assert quota_manager.has_quota_available("polymarket", progress) is True


def test_has_quota_available_false(quota_manager):
    """Test quota availability check when quota is exhausted."""
    progress = CollectionProgress()
    
    # Fill quota
    for i in range(50):
        q = create_test_question(
            id=f"q_{i}",
            source_name="polymarket"
        )
        progress.add_question(q)
    
    assert quota_manager.has_quota_available("polymarket", progress) is False


def test_calculate_needed_with_type_gaps():
    """Test calculation considers type gaps."""
    goal = CollectionGoal(
        total_questions=100,
        type_distribution={"boolean": 50, "mcq": 50},
        source_quotas={"polymarket": 100}
    )
    manager = QuotaManager(goal)
    
    progress = CollectionProgress()
    
    # Add 40 boolean questions (need 10 more)
    for i in range(40):
        q = create_test_question(
            id=f"q_{i}",
            source_name="polymarket"
        )
        progress.add_question(q)
    
    # Should be limited by type gap (10) + mcq gap (50) = 60
    needed = manager.calculate_needed_from_source("polymarket", progress)
    assert needed == 60
