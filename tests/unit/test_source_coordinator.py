"""Unit tests for SourceCoordinator."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from src.pipelines.collection.coordinator import SourceCoordinator, SourceRequest
from src.pipelines.collection.runner_base import QuestionSourceRunner, CollectionResult
from tests.conftest import create_test_question


@pytest.fixture
def mock_runner():
    """Create a mock question source runner."""
    runner = MagicMock(spec=QuestionSourceRunner)
    runner.collect = AsyncMock()
    return runner


@pytest.fixture
def sample_question():
    """Create a sample question."""
    return create_test_question(id="q_1", source_name="test")


@pytest.mark.asyncio
async def test_coordinator_parallel_mode():
    """Test coordinator initializes in parallel mode."""
    coordinator = SourceCoordinator(parallel=True)
    assert coordinator.parallel is True


@pytest.mark.asyncio
async def test_coordinator_sequential_mode():
    """Test coordinator initializes in sequential mode."""
    coordinator = SourceCoordinator(parallel=False)
    assert coordinator.parallel is False


@pytest.mark.asyncio
async def test_collect_from_single_source(mock_runner, sample_question):
    """Test collection from a single source."""
    coordinator = SourceCoordinator(parallel=True)

    # Setup mock
    expected_result = CollectionResult(
        source_name="test_source",
        questions=[sample_question],
        requested_count=1,
        actual_count=1,
        success=True,
    )
    mock_runner.collect.return_value = expected_result

    # Create request
    request = SourceRequest(source_name="test_source", runner=mock_runner, count=1)

    # Execute
    results = await coordinator.collect_from_sources([request])

    # Verify
    assert len(results) == 1
    assert results[0] == expected_result
    assert results[0].success is True
    assert len(results[0].questions) == 1
    mock_runner.collect.assert_called_once()


@pytest.mark.asyncio
async def test_collect_parallel_multiple_sources(sample_question):
    """Test parallel collection from multiple sources."""
    coordinator = SourceCoordinator(parallel=True)

    # Create multiple mock runners
    runner1 = MagicMock(spec=QuestionSourceRunner)
    runner1.collect = AsyncMock(
        return_value=CollectionResult(
            source_name="source1",
            questions=[sample_question],
            requested_count=1,
            actual_count=1,
            success=True,
        )
    )

    runner2 = MagicMock(spec=QuestionSourceRunner)
    runner2.collect = AsyncMock(
        return_value=CollectionResult(
            source_name="source2",
            questions=[sample_question],
            requested_count=1,
            actual_count=1,
            success=True,
        )
    )

    requests = [
        SourceRequest(source_name="source1", runner=runner1, count=1),
        SourceRequest(source_name="source2", runner=runner2, count=1),
    ]

    # Execute
    results = await coordinator.collect_from_sources(requests)

    # Verify
    assert len(results) == 2
    assert all(r.success for r in results)
    runner1.collect.assert_called_once()
    runner2.collect.assert_called_once()


@pytest.mark.asyncio
async def test_collect_sequential_multiple_sources(sample_question):
    """Test sequential collection from multiple sources."""
    coordinator = SourceCoordinator(parallel=False)

    # Create multiple mock runners
    runner1 = MagicMock(spec=QuestionSourceRunner)
    runner1.collect = AsyncMock(
        return_value=CollectionResult(
            source_name="source1",
            questions=[sample_question],
            requested_count=1,
            actual_count=1,
            success=True,
        )
    )

    runner2 = MagicMock(spec=QuestionSourceRunner)
    runner2.collect = AsyncMock(
        return_value=CollectionResult(
            source_name="source2",
            questions=[sample_question],
            requested_count=1,
            actual_count=1,
            success=True,
        )
    )

    requests = [
        SourceRequest(source_name="source1", runner=runner1, count=1),
        SourceRequest(source_name="source2", runner=runner2, count=1),
    ]

    # Execute
    results = await coordinator.collect_from_sources(requests)

    # Verify
    assert len(results) == 2
    assert all(r.success for r in results)


@pytest.mark.asyncio
async def test_collect_handles_exceptions_parallel():
    """Test that parallel collection handles exceptions gracefully."""
    coordinator = SourceCoordinator(parallel=True)

    # Create runner that raises exception
    runner_error = MagicMock(spec=QuestionSourceRunner)
    runner_error.collect = AsyncMock(side_effect=Exception("Test error"))

    # Create normal runner
    runner_ok = MagicMock(spec=QuestionSourceRunner)
    runner_ok.collect = AsyncMock(
        return_value=CollectionResult(
            source_name="ok_source",
            questions=[],
            requested_count=1,
            actual_count=0,
            success=True,
        )
    )

    requests = [
        SourceRequest(source_name="error_source", runner=runner_error, count=1),
        SourceRequest(source_name="ok_source", runner=runner_ok, count=1),
    ]

    # Execute
    results = await coordinator.collect_from_sources(requests)

    # Should have 2 results (failed source included as CollectionResult with success=False)
    assert len(results) == 2
    error_result = [r for r in results if r.source_name == "error_source"][0]
    ok_result = [r for r in results if r.source_name == "ok_source"][0]
    assert error_result.success is False
    assert error_result.error_message is not None
    assert "Test error" in error_result.error_message
    assert ok_result.success is True


@pytest.mark.asyncio
async def test_collect_handles_exceptions_sequential():
    """Test that sequential collection handles exceptions gracefully."""
    coordinator = SourceCoordinator(parallel=False)

    # Create runner that raises exception
    runner_error = MagicMock(spec=QuestionSourceRunner)
    runner_error.collect = AsyncMock(side_effect=Exception("Test error"))

    # Create normal runner
    runner_ok = MagicMock(spec=QuestionSourceRunner)
    runner_ok.collect = AsyncMock(
        return_value=CollectionResult(
            source_name="ok_source",
            questions=[],
            requested_count=1,
            actual_count=0,
            success=True,
        )
    )

    requests = [
        SourceRequest(source_name="error_source", runner=runner_error, count=1),
        SourceRequest(source_name="ok_source", runner=runner_ok, count=1),
    ]

    # Execute
    results = await coordinator.collect_from_sources(requests)

    # Should have 2 results (failed source included as CollectionResult with success=False)
    assert len(results) == 2
    error_result = [r for r in results if r.source_name == "error_source"][0]
    ok_result = [r for r in results if r.source_name == "ok_source"][0]
    assert error_result.success is False
    assert error_result.error_message is not None
    assert "Test error" in error_result.error_message
    assert ok_result.success is True


@pytest.mark.asyncio
async def test_source_request_with_filters(mock_runner, sample_question):
    """Test source request with type and category filters."""
    coordinator = SourceCoordinator(parallel=True)

    # Setup mock
    mock_runner.collect.return_value = CollectionResult(
        source_name="test",
        questions=[sample_question],
        requested_count=1,
        actual_count=1,
        success=True,
    )

    # Create request with filters
    request = SourceRequest(
        source_name="test",
        runner=mock_runner,
        count=5,
        type_filter=["boolean", "mcq"],
        category_filter={"tech": 3, "politics": 2},
        existing_question_ids={"q_old_1", "q_old_2"},
    )

    # Execute
    results = await coordinator.collect_from_sources([request])

    # Verify runner was called with correct arguments
    mock_runner.collect.assert_called_once_with(
        count=5,
        type_filter=["boolean", "mcq"],
        category_filter={"tech": 3, "politics": 2},
        quality_requirements=None,
        existing_question_ids={"q_old_1", "q_old_2"},
        time_horizon_hints=None,
    )


@pytest.mark.asyncio
async def test_collect_empty_requests():
    """Test collection with empty request list."""
    coordinator = SourceCoordinator(parallel=True)

    results = await coordinator.collect_from_sources([])

    assert results == []
