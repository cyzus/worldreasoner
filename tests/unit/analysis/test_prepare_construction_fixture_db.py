from typing import Any, Dict, Optional

from scripts.analysis.prepare_construction_fixture_db import (
    infer_actual_outcome_id,
)


def _outcome(
    outcome_id: str,
    title: str,
    *,
    option_index: Optional[int] = None,
    is_actual: Optional[bool] = None,
) -> Dict[str, Any]:
    return {
        "id": outcome_id,
        "title": title,
        "outcome_option_index": option_index,
        "is_actual_outcome": is_actual,
    }


def test_preserves_existing_actual_outcome() -> None:
    outcomes = [
        _outcome("yes", "Yes - question", is_actual=True),
        _outcome("no", "No - question", is_actual=False),
    ]

    assert infer_actual_outcome_id('"No"', '["Yes", "No"]', outcomes) == "yes"


def test_infers_timeframe_from_unique_title_match() -> None:
    outcomes = [
        _outcome("closed", "Microsoft closes acquisition in Q4 2023"),
        _outcome("failed", "Microsoft fails to close acquisition in Q4 2023"),
    ]

    assert infer_actual_outcome_id('"Q4 2023"', None, outcomes) == "closed"


def test_infers_second_option_from_no_outcome() -> None:
    outcomes = [
        _outcome("yes", "Yes - Slovakia vs Finland"),
        _outcome("no", "No - Slovakia vs Finland"),
    ]

    assert (
        infer_actual_outcome_id(
            '"Finland"',
            '["Slovakia", "Finland"]',
            outcomes,
        )
        == "no"
    )


def test_does_not_guess_ambiguous_outcome() -> None:
    outcomes = [
        _outcome("one", "Scenario one"),
        _outcome("two", "Scenario two"),
    ]

    assert infer_actual_outcome_id('"Unknown"', None, outcomes) is None
