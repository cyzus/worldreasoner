"""Tests for AutoBenchmarkService."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.domain.evaluation.auto_benchmark import (
    AutoBenchmarkService,
    ConditionResult,
)
from src.domain.evaluation.conditions import (
    ConditionName,
    EXPERIMENT_CONDITIONS,
)


def _make_question(
    qid="q_test_001",
    resolution_date=None,
    ground_truth=True,
):
    """Create a mock question for testing."""
    q = MagicMock()
    q.id = qid
    q.question_text = f"Test question {qid}"
    q.ground_truth = ground_truth
    q.resolution_date = resolution_date or datetime(2025, 6, 1, tzinfo=timezone.utc)
    q.question_type = MagicMock()
    q.question_type.value = "binary"
    q.domain = MagicMock()
    q.domain.value = "politics"
    q.source = "test"
    q.prepare_forecast = MagicMock(
        return_value={
            "simulated_date": q.resolution_date - timedelta(days=7),
            "window_start": q.resolution_date - timedelta(days=30),
            "window_end": q.resolution_date,
        }
    )
    return q


class TestComputeSimulatedDate:
    """Tests for _compute_simulated_date."""

    def test_oracle_uses_resolution_minus_one(self):
        service = AutoBenchmarkService.__new__(AutoBenchmarkService)
        service.db = MagicMock()

        question = _make_question()
        oracle_condition = EXPERIMENT_CONDITIONS[ConditionName.ORACLE]

        result = service._compute_simulated_date(question, oracle_condition)

        expected = question.resolution_date - timedelta(days=1)
        assert result == expected

    def test_non_oracle_uses_slot(self):
        service = AutoBenchmarkService.__new__(AutoBenchmarkService)
        service.db = MagicMock()

        question = _make_question()
        vanilla_condition = EXPERIMENT_CONDITIONS[ConditionName.VANILLA_LLM]
        expected_date = question.resolution_date - timedelta(days=14)

        with patch(
            "src.domain.evaluation.auto_benchmark.get_forecast_date_for_slot",
            return_value={"simulated_date": expected_date},
        ) as mock_get_slot:
            result = service._compute_simulated_date(question, vanilla_condition, slot="mid")

            mock_get_slot.assert_called_once()
            assert result == expected_date

    def test_fallback_on_slot_error(self):
        service = AutoBenchmarkService.__new__(AutoBenchmarkService)
        service.db = MagicMock()

        question = _make_question()
        vanilla_condition = EXPERIMENT_CONDITIONS[ConditionName.VANILLA_LLM]

        with patch(
            "src.domain.evaluation.auto_benchmark.get_forecast_date_for_slot",
            side_effect=ValueError("No context"),
        ):
            result = service._compute_simulated_date(question, vanilla_condition, slot="mid")

        # Fallback: resolution_date - 1 day
        expected = question.resolution_date - timedelta(days=1)
        assert result == expected


class TestAggregateConditionMetrics:
    """Tests for _aggregate_condition_metrics."""

    def test_all_successful(self):
        results = [
            {"status": "success", "is_correct": True, "brier_score": 0.1, "log_score": -0.1},
            {"status": "success", "is_correct": False, "brier_score": 0.6, "log_score": -0.9},
            {"status": "success", "is_correct": True, "brier_score": 0.2, "log_score": -0.2},
        ]

        metrics = AutoBenchmarkService._aggregate_condition_metrics(results)

        assert metrics["total"] == 3
        assert metrics["successful"] == 3
        assert metrics["failed"] == 0
        assert metrics["accuracy"] == pytest.approx(2 / 3)
        assert metrics["avg_brier_score"] == pytest.approx(0.3)
        assert metrics["avg_log_score"] == pytest.approx(-0.4)

    def test_with_failures(self):
        results = [
            {"status": "success", "is_correct": True, "brier_score": 0.1, "log_score": -0.1},
            {"status": "error", "error": "Agent failed"},
        ]

        metrics = AutoBenchmarkService._aggregate_condition_metrics(results)

        assert metrics["total"] == 2
        assert metrics["successful"] == 1
        assert metrics["failed"] == 1
        assert metrics["accuracy"] == 1.0

    def test_all_failures(self):
        results = [
            {"status": "error", "error": "fail1"},
            {"status": "error", "error": "fail2"},
        ]

        metrics = AutoBenchmarkService._aggregate_condition_metrics(results)

        assert metrics["total"] == 2
        assert metrics["successful"] == 0
        assert metrics["failed"] == 2
        assert metrics["accuracy"] == 0.0
        assert metrics["avg_brier_score"] is None
        assert metrics["avg_log_score"] is None

    def test_empty_results(self):
        metrics = AutoBenchmarkService._aggregate_condition_metrics([])
        assert metrics["total"] == 0
        assert metrics["successful"] == 0

    def test_none_scores_excluded(self):
        results = [
            {"status": "success", "is_correct": True, "brier_score": 0.2, "log_score": None},
            {"status": "success", "is_correct": True, "brier_score": None, "log_score": -0.3},
        ]

        metrics = AutoBenchmarkService._aggregate_condition_metrics(results)

        assert metrics["avg_brier_score"] == pytest.approx(0.2)
        assert metrics["avg_log_score"] == pytest.approx(-0.3)


class TestBuildComparativeSummary:
    """Tests for _build_comparative_summary."""

    def test_leaderboard_sorted_by_accuracy_then_brier(self):
        condition_results = {
            "vanilla_llm": {
                "model_a": ConditionResult(
                    condition_name="vanilla_llm",
                    display_name="Vanilla LLM",
                    model_name="model_a",
                    total_questions=10,
                    successful=10,
                    accuracy=0.3,
                    avg_brier_score=0.5,
                ),
            },
            "worldreasoner": {
                "model_a": ConditionResult(
                    condition_name="worldreasoner",
                    display_name="WorldReasoner Agent",
                    model_name="model_a",
                    total_questions=10,
                    successful=10,
                    accuracy=0.8,
                    avg_brier_score=0.15,
                ),
            },
            "oracle": {
                "model_a": ConditionResult(
                    condition_name="oracle",
                    display_name="Oracle Agent",
                    model_name="model_a",
                    total_questions=10,
                    successful=10,
                    accuracy=0.8,
                    avg_brier_score=0.08,
                ),
            },
        }

        summary = AutoBenchmarkService._build_comparative_summary(condition_results)
        leaderboard = summary["leaderboard"]

        assert len(leaderboard) == 3
        # Oracle and WorldReasoner tied on accuracy, Oracle wins on Brier
        assert leaderboard[0]["condition"] == "oracle"
        assert leaderboard[1]["condition"] == "worldreasoner"
        assert leaderboard[2]["condition"] == "vanilla_llm"

    def test_empty_results(self):
        summary = AutoBenchmarkService._build_comparative_summary({})
        assert summary["leaderboard"] == []

    def test_multi_model_leaderboard(self):
        condition_results = {
            "vanilla_llm": {
                "model_a": ConditionResult(
                    condition_name="vanilla_llm",
                    display_name="Vanilla LLM",
                    model_name="model_a",
                    total_questions=5,
                    successful=5,
                    accuracy=0.4,
                    avg_brier_score=0.4,
                ),
                "model_b": ConditionResult(
                    condition_name="vanilla_llm",
                    display_name="Vanilla LLM",
                    model_name="model_b",
                    total_questions=5,
                    successful=5,
                    accuracy=0.6,
                    avg_brier_score=0.3,
                ),
            },
        }

        summary = AutoBenchmarkService._build_comparative_summary(condition_results)
        leaderboard = summary["leaderboard"]

        assert len(leaderboard) == 2
        assert leaderboard[0]["model"] == "model_b"
        assert leaderboard[1]["model"] == "model_a"


class TestCheckAlreadyCompleted:
    """Tests for resume skip logic."""

    def test_returns_true_when_matching_forecast_exists(self):
        service = AutoBenchmarkService.__new__(AutoBenchmarkService)
        service.db = MagicMock()

        forecast = MagicMock()
        forecast.evaluation_metadata = {
            "benchmark_condition": "vanilla_llm",
            "benchmark_model": "model_a",
        }
        service.db.get_many = MagicMock(return_value=[forecast])

        question = _make_question()
        condition = EXPERIMENT_CONDITIONS[ConditionName.VANILLA_LLM]

        assert service._check_already_completed(condition, question, "model_a") is True

    def test_returns_false_when_no_matching_forecast(self):
        service = AutoBenchmarkService.__new__(AutoBenchmarkService)
        service.db = MagicMock()

        forecast = MagicMock()
        forecast.evaluation_metadata = {
            "benchmark_condition": "oracle",
            "benchmark_model": "model_a",
        }
        service.db.get_many = MagicMock(return_value=[forecast])

        question = _make_question()
        condition = EXPERIMENT_CONDITIONS[ConditionName.VANILLA_LLM]

        assert service._check_already_completed(condition, question, "model_a") is False

    def test_returns_false_when_no_forecasts(self):
        service = AutoBenchmarkService.__new__(AutoBenchmarkService)
        service.db = MagicMock()
        service.db.get_many = MagicMock(return_value=[])

        question = _make_question()
        condition = EXPERIMENT_CONDITIONS[ConditionName.VANILLA_LLM]

        assert service._check_already_completed(condition, question, "model_a") is False

    def test_returns_false_when_metadata_is_none(self):
        service = AutoBenchmarkService.__new__(AutoBenchmarkService)
        service.db = MagicMock()

        forecast = MagicMock()
        forecast.evaluation_metadata = None
        service.db.get_many = MagicMock(return_value=[forecast])

        question = _make_question()
        condition = EXPERIMENT_CONDITIONS[ConditionName.VANILLA_LLM]

        assert service._check_already_completed(condition, question, "model_a") is False


class TestResumeResultLoading:
    """Tests for loading stored metrics during resumed benchmark runs."""

    def test_loads_latest_evaluated_result_for_resume(self, tmp_path):
        db_path = tmp_path / "resume.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE forecasts (
                id TEXT,
                question_id TEXT,
                prediction TEXT,
                confidence REAL,
                is_correct INTEGER,
                brier_score REAL,
                log_score REAL,
                simulated_date TEXT,
                timestamp TEXT,
                evaluation_metadata TEXT
            )
            """
        )

        meta = json.dumps(
            {
                "benchmark_condition": "worldreasoner",
                "benchmark_model": "model_a",
            }
        )
        rows = [
            (
                "old_forecast",
                "q1",
                "false",
                0.6,
                0,
                0.36,
                -0.9,
                "2025-01-01T00:00:00+00:00",
                "2025-01-02T00:00:00+00:00",
                meta,
            ),
            (
                "new_forecast",
                "q1",
                "true",
                0.8,
                1,
                0.04,
                -0.2,
                "2025-01-01T00:00:00+00:00",
                "2025-01-03T00:00:00+00:00",
                meta,
            ),
            (
                "unevaluated_forecast",
                "q2",
                "true",
                0.8,
                None,
                None,
                None,
                "2025-01-01T00:00:00+00:00",
                "2025-01-03T00:00:00+00:00",
                meta,
            ),
        ]
        conn.executemany(
            "INSERT INTO forecasts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        conn.close()

        service = AutoBenchmarkService.__new__(AutoBenchmarkService)
        service.db = MagicMock()
        service.db.db_path = db_path

        results = service._load_completed_resume_results()

        assert set(results) == {("q1", "worldreasoner", "model_a")}
        loaded = results[("q1", "worldreasoner", "model_a")]
        assert loaded["forecast_id"] == "new_forecast"
        assert loaded["is_correct"] is True
        assert loaded["accuracy"] == 1.0
        assert loaded["brier_score"] == pytest.approx(0.04)
        assert loaded["log_score"] == pytest.approx(-0.2)
        assert loaded["prediction"] is True
        assert loaded["skipped_resume"] is True
