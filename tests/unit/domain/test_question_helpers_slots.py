"""Unit tests for ForecastSlot and get_forecast_date_for_slot()."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from src.domain.models.question_helpers import (
    ForecastSlot,
    MIN_EFFECTIVE_SLOT_WINDOW_DAYS,
    SLOT_FRACTIONS,
    get_forecast_date_for_slot,
)
from src.domain.models import Question
from src.domain.models.question import QuestionType
from src.utils.enums import Domain


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_question(resolution_days_from_now: int = 90) -> Question:
    """Create a minimal Question with a resolution date."""
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return Question(
        id="test_q",
        question_text="Will this question resolve as expected?",
        question_type=QuestionType.BINARY,
        domain=Domain.POLITICS,
        source="test",
        difficulty=3,
        resolution_date=now + timedelta(days=resolution_days_from_now),
        estimated_start_time=now,
    )


def _window_start_for(question: Question, days_before_resolution: int = 30) -> datetime:
    """Return a synthetic window_start (resolution - N days)."""
    return question.resolution_date - timedelta(days=days_before_resolution)


# ---------------------------------------------------------------------------
# ForecastSlot enum
# ---------------------------------------------------------------------------

class TestForecastSlotEnum:
    def test_values_are_strings(self):
        assert ForecastSlot.EARLY.value == "early"
        assert ForecastSlot.MID.value == "mid"
        assert ForecastSlot.LATE.value == "late"

    def test_fractions_sum_covers_range(self):
        """Fractions should be in (0, 1) and ordered early < mid < late."""
        fractions = [SLOT_FRACTIONS[s] for s in ForecastSlot]
        assert all(0 < f < 1 for f in fractions)
        assert fractions[0] < fractions[1] < fractions[2]

    def test_parse_from_string(self):
        assert ForecastSlot("mid") == ForecastSlot.MID
        assert ForecastSlot("early") == ForecastSlot.EARLY
        assert ForecastSlot("late") == ForecastSlot.LATE

    def test_invalid_string_raises(self):
        with pytest.raises(ValueError):
            ForecastSlot("bogus")


# ---------------------------------------------------------------------------
# get_forecast_date_for_slot
# ---------------------------------------------------------------------------

class TestGetForecastDateForSlot:
    """Tests for get_forecast_date_for_slot()."""

    def _call_with_fixed_window(
        self,
        question: Question,
        slot: ForecastSlot,
        window_start: datetime,
        window_end: datetime,
    ) -> dict:
        """Helper: patch calculate_forecast_context_window and call the function."""
        with patch(
            "src.domain.models.question_helpers.calculate_forecast_context_window",
            return_value=(window_start, window_end),
        ):
            return get_forecast_date_for_slot(question, slot=slot, db=None)

    def test_mid_slot_is_midpoint(self):
        """Mid slot should return exactly 50% between window_start and window_end."""
        q = _make_question(90)
        w_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        w_end = datetime(2024, 4, 1, tzinfo=timezone.utc)  # 91-day window

        result = self._call_with_fixed_window(q, ForecastSlot.MID, w_start, w_end)

        span = w_end - w_start
        expected = w_start + span * 0.50
        assert result["simulated_date"] == expected

    def test_early_slot(self):
        """Early slot should return 20% into the window."""
        q = _make_question(90)
        w_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        w_end = datetime(2024, 4, 1, tzinfo=timezone.utc)

        result = self._call_with_fixed_window(q, ForecastSlot.EARLY, w_start, w_end)

        span = w_end - w_start
        expected = w_start + span * 0.20
        assert result["simulated_date"] == expected

    def test_late_slot(self):
        """Late slot should return 80% into the window."""
        q = _make_question(90)
        w_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        w_end = datetime(2024, 4, 1, tzinfo=timezone.utc)

        result = self._call_with_fixed_window(q, ForecastSlot.LATE, w_start, w_end)

        span = w_end - w_start
        expected = w_start + span * 0.80
        assert result["simulated_date"] == expected

    def test_result_contains_expected_keys(self):
        """Return dict should have all documented keys."""
        q = _make_question(90)
        w_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        w_end = datetime(2024, 4, 1, tzinfo=timezone.utc)

        result = self._call_with_fixed_window(q, ForecastSlot.MID, w_start, w_end)

        assert "simulated_date" in result
        assert "window_start" in result
        assert "window_end" in result
        assert "slot" in result
        assert "horizon_days" in result
        assert result["slot"] == "mid"

    def test_horizon_days_is_window_span(self):
        """horizon_days should equal window_end - window_start in days."""
        q = _make_question(90)
        w_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        w_end = datetime(2024, 4, 1, tzinfo=timezone.utc)

        result = self._call_with_fixed_window(q, ForecastSlot.MID, w_start, w_end)

        assert result["horizon_days"] == (w_end - w_start).days

    def test_proportional_consistency_across_horizons(self):
        """
        Mid slot on a 7-day window and on a 90-day window should both be at
        exactly 50% of their respective window spans — consistent difficulty.
        """
        q = _make_question(90)

        short_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        short_end   = datetime(2024, 1, 8, tzinfo=timezone.utc)  # 7-day window

        long_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        long_end   = datetime(2024, 4, 1, tzinfo=timezone.utc)  # ~90-day window

        short_result = self._call_with_fixed_window(q, ForecastSlot.MID, short_start, short_end)
        long_result  = self._call_with_fixed_window(q, ForecastSlot.MID, long_start, long_end)

        short_fraction = (
            (short_result["simulated_date"] - short_start) / (short_end - short_start)
        )
        long_fraction = (
            (long_result["simulated_date"] - long_start) / (long_end - long_start)
        )

        assert abs(short_fraction - long_fraction) < 1e-9  # Both should be exactly 0.5

    def test_simulated_date_is_before_window_end(self):
        """Simulated date must always be strictly before window_end."""
        q = _make_question(90)
        w_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        w_end = datetime(2024, 4, 1, tzinfo=timezone.utc)

        for slot in ForecastSlot:
            result = self._call_with_fixed_window(q, slot, w_start, w_end)
            assert result["simulated_date"] < w_end, f"Slot {slot} exceeded window_end"

    def test_simulated_date_is_after_window_start(self):
        """Simulated date must always be strictly after window_start."""
        q = _make_question(90)
        w_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        w_end = datetime(2024, 4, 1, tzinfo=timezone.utc)

        for slot in ForecastSlot:
            result = self._call_with_fixed_window(q, slot, w_start, w_end)
            assert result["simulated_date"] > w_start, f"Slot {slot} was before window_start"

    def test_default_slot_is_mid(self):
        """When no slot argument is given, should default to MID."""
        q = _make_question(90)
        w_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        w_end = datetime(2024, 4, 1, tzinfo=timezone.utc)

        with patch(
            "src.domain.models.question_helpers.calculate_forecast_context_window",
            return_value=(w_start, w_end),
        ):
            result = get_forecast_date_for_slot(q, db=None)

        assert result["slot"] == "mid"
        span = w_end - w_start
        assert result["simulated_date"] == w_start + span * 0.50

    def test_narrow_window_is_expanded_for_stable_slots(self):
        """Very narrow windows should be backfilled before slot placement."""
        q = _make_question(90)
        w_start = datetime(2024, 3, 31, tzinfo=timezone.utc)
        w_end = datetime(2024, 4, 1, tzinfo=timezone.utc)

        result = self._call_with_fixed_window(q, ForecastSlot.MID, w_start, w_end)

        expected_start = w_end - timedelta(days=MIN_EFFECTIVE_SLOT_WINDOW_DAYS)
        expected_mid = expected_start + (w_end - expected_start) * 0.50

        assert result["window_start"] == expected_start
        assert result["simulated_date"] == expected_mid
        assert result["simulated_date"].date() < w_start.date()
