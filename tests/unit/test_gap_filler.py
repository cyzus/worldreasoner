"""Unit tests for GapFiller."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from src.pipelines.collection.gap_filler import GapFiller
from src.pipelines.collection.gap_analyzer import GapAnalysis
from src.pipelines.collection.coordinator import SourceCoordinator
from src.pipelines.collection.progress import CollectionProgress
from src.pipelines.collection.runner_base import QuestionSourceRunner, CollectionResult
from src.config.collection_goal import CollectionGoal
from tests.conftest import create_test_question


@pytest.fixture
def sample_goal():
    """Create sample collection goal."""
    return CollectionGoal(
        total_questions=100,
        type_distribution={"binary": 50, "mcq": 50},
        source_minimums={"source1": 60, "source2": 40},
    )


@pytest.fixture
def mock_runner():
    """Create a mock question source runner."""
    runner = MagicMock(spec=QuestionSourceRunner)
    runner.collect = AsyncMock()
    runner.can_provide = AsyncMock(return_value=True)
    return runner


@pytest.fixture
def coordinator():
    """Create source coordinator."""
    return SourceCoordinator(parallel=False)


@pytest.fixture
def gap_filler(sample_goal, coordinator):
    """Create gap filler with mock sources."""
    sources = {}
    return GapFiller(sources, coordinator, sample_goal)


def test_gap_filler_initialization(sample_goal, coordinator):
    """Test gap filler initializes correctly."""
    sources = {"source1": MagicMock(), "source2": MagicMock()}
    filler = GapFiller(sources, coordinator, sample_goal)

    assert filler.sources == sources
    assert filler.coordinator == coordinator
    assert filler.goal == sample_goal
    assert len(filler.exhausted_sources) == 0


@pytest.mark.asyncio
async def test_fill_gaps_no_gaps(gap_filler):
    """Test gap filling when no gaps exist."""
    analysis = GapAnalysis(type_gaps={}, category_gaps={}, total_needed=0)
    

    questions = await gap_filler.fill_gaps(analysis, set())

    assert questions == []


@pytest.mark.asyncio
async def test_fill_type_gap(sample_goal, coordinator, mock_runner):
    """Test filling a type gap."""
    sources = {"source1": mock_runner}
    filler = GapFiller(sources, coordinator, sample_goal)

    # Setup mock
    sample_q = create_test_question(
        id="q_1", question_type="binary", source_name="source1"
    )
    mock_runner.collect.return_value = CollectionResult(
        source_name="source1",
        questions=[sample_q],
        requested_count=5,
        actual_count=1,
        success=True,
    )

    # Create analysis with type gap
    analysis = GapAnalysis(type_gaps={"binary": 5}, category_gaps={}, total_needed=5)
    

    # Fill gaps
    questions = await filler.fill_gaps(analysis, set())

    assert len(questions) == 1
    assert questions[0].id == "q_1"
    mock_runner.can_provide.assert_called_with(question_type="binary")


@pytest.mark.asyncio
async def test_fill_category_gap(sample_goal, coordinator, mock_runner):
    """Test filling a category gap."""
    sources = {"source1": mock_runner}
    filler = GapFiller(sources, coordinator, sample_goal)

    # Setup mock
    sample_q = create_test_question(
        id="q_1", question_type="binary", category="tech", source_name="source1"
    )
    mock_runner.collect.return_value = CollectionResult(
        source_name="source1",
        questions=[sample_q],
        requested_count=5,
        actual_count=1,
        success=True,
    )

    # Create analysis with category gap
    analysis = GapAnalysis(type_gaps={}, category_gaps={"tech": 5}, total_needed=5)
    

    # Fill gaps
    questions = await filler.fill_gaps(analysis, set())

    assert len(questions) == 1
    assert questions[0].category == "tech"
    mock_runner.can_provide.assert_called_with(category="tech")


@pytest.mark.asyncio
async def test_fill_gaps_source_exhausted(sample_goal, coordinator, mock_runner):
    """Test that exhausted sources are skipped."""
    sources = {"source1": mock_runner}
    filler = GapFiller(sources, coordinator, sample_goal)

    # Mark source as exhausted
    filler.exhausted_sources.add("source1")

    # Create analysis
    analysis = GapAnalysis(type_gaps={"binary": 5}, category_gaps={}, total_needed=5)
    

    # Fill gaps - should skip exhausted source
    questions = await filler.fill_gaps(analysis, set())

    assert questions == []
    # Runner should not be called
    mock_runner.collect.assert_not_called()


@pytest.mark.asyncio
async def test_fill_gaps_source_cannot_provide(sample_goal, coordinator, mock_runner):
    """Test that sources that can't provide are skipped."""
    sources = {"source1": mock_runner}
    filler = GapFiller(sources, coordinator, sample_goal)

    # Mock can_provide to return False
    mock_runner.can_provide = AsyncMock(return_value=False)

    # Create analysis
    analysis = GapAnalysis(type_gaps={"binary": 5}, category_gaps={}, total_needed=5)
    

    # Fill gaps
    questions = await filler.fill_gaps(analysis, set())

    assert questions == []
    mock_runner.collect.assert_not_called()


@pytest.mark.asyncio
async def test_fill_gaps_quota_exceeded(sample_goal, coordinator, mock_runner):
    """Test that sources at quota limit still collect but return empty if nothing new."""
    sources = {"source1": mock_runner}
    filler = GapFiller(sources, coordinator, sample_goal)

    # Setup mock to return empty result (simulating no new questions available)
    mock_runner.collect = AsyncMock(
        return_value=CollectionResult(
            source_name="source1",
            questions=[],
            requested_count=10,
            actual_count=0,
            success=True,
        )
    )

    # Create analysis
    analysis = GapAnalysis(type_gaps={"binary": 5}, category_gaps={}, total_needed=5)

    # Fill gaps - source still gets called (quota is not enforced at GapFiller level)
    questions = await filler.fill_gaps(analysis, set())

    assert questions == []


@pytest.mark.asyncio
async def test_fill_gaps_marks_source_exhausted_on_failure(
    sample_goal, coordinator, mock_runner
):
    """Test that sources returning failure are marked exhausted."""
    sources = {"source1": mock_runner}
    filler = GapFiller(sources, coordinator, sample_goal)

    # Setup mock to return a FAILED result (success=False marks exhausted)
    mock_runner.collect = AsyncMock(
        return_value=CollectionResult(
            source_name="source1",
            questions=[],
            requested_count=5,
            actual_count=0,
            success=False,
            error_message="Source exhausted",
        )
    )

    # Create analysis
    analysis = GapAnalysis(type_gaps={"binary": 5}, category_gaps={}, total_needed=5)
    

    # Fill gaps
    questions = await filler.fill_gaps(analysis, set())

    assert questions == []
    assert "source1" in filler.exhausted_sources


@pytest.mark.asyncio
async def test_reset_exhausted():
    """Test reset_exhausted clears exhausted sources."""
    sources = {}
    coordinator = SourceCoordinator(parallel=False)
    goal = CollectionGoal(total_questions=10)
    filler = GapFiller(sources, coordinator, goal)

    # Add some exhausted sources
    filler.exhausted_sources.add("source1")
    filler.exhausted_sources.add("source2")
    assert len(filler.exhausted_sources) == 2

    # Reset
    filler.reset_exhausted()
    assert len(filler.exhausted_sources) == 0


@pytest.mark.asyncio
async def test_fill_multiple_gaps_incrementally(sample_goal, coordinator):
    """Test filling multiple gaps stops when count is reached."""
    # Create two mock runners
    runner1 = MagicMock(spec=QuestionSourceRunner)
    runner1.can_provide = AsyncMock(return_value=True)
    runner2 = MagicMock(spec=QuestionSourceRunner)
    runner2.can_provide = AsyncMock(return_value=True)

    # Setup runner1 to return 3 questions
    q1 = create_test_question(id="q_1", question_type="binary", source_name="source1")
    q2 = create_test_question(id="q_2", question_type="binary", source_name="source1")
    q3 = create_test_question(id="q_3", question_type="binary", source_name="source1")
    runner1.collect.return_value = CollectionResult(
        source_name="source1",
        questions=[q1, q2, q3],
        requested_count=5,
        actual_count=3,
        success=True,
    )

    # Setup runner2 to return 2 questions
    q4 = create_test_question(id="q_4", question_type="binary", source_name="source2")
    q5 = create_test_question(id="q_5", question_type="binary", source_name="source2")
    runner2.collect.return_value = CollectionResult(
        source_name="source2",
        questions=[q4, q5],
        requested_count=2,
        actual_count=2,
        success=True,
    )

    sources = {"source1": runner1, "source2": runner2}
    filler = GapFiller(sources, coordinator, sample_goal)

    # Need 5 boolean questions
    analysis = GapAnalysis(type_gaps={"binary": 5}, category_gaps={}, total_needed=5)
    

    # Fill gaps
    questions = await filler.fill_gaps(analysis, set())

    # Should get all 5 questions (3 from source1, 2 from source2)
    assert len(questions) == 5
    assert questions[0].id == "q_1"
    assert questions[4].id == "q_5"
