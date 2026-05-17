import pytest

from src.domain.evaluation.metrics import (
    calculate_accuracy,
    calculate_brier_score,
    calculate_log_score,
)
from src.domain.models.question import QuestionType


@pytest.mark.parametrize(
    ("prediction", "ground_truth"),
    [
        (True, '"Yes"'),
        (False, '"No"'),
        ("true", '"Yes"'),
        ("false", '"No"'),
        ("Yes", True),
        ("No", False),
    ],
)
def test_binary_accuracy_normalizes_bool_and_json_yes_no(
    prediction,
    ground_truth,
):
    assert calculate_accuracy(prediction, ground_truth, QuestionType.BINARY) == 1.0


@pytest.mark.parametrize(
    ("prediction", "ground_truth", "expected"),
    [
        (True, '"Yes"', 0.0004),
        (False, '"No"', 0.0004),
        (True, '"No"', 0.9604),
        (False, '"Yes"', 0.9604),
    ],
)
def test_binary_brier_normalizes_ground_truth_strings(
    prediction,
    ground_truth,
    expected,
):
    assert (
        calculate_brier_score(prediction, ground_truth, 0.98, QuestionType.BINARY)
        == pytest.approx(expected)
    )


@pytest.mark.parametrize(
    ("prediction", "ground_truth"),
    [
        (True, '"Yes"'),
        (False, '"No"'),
    ],
)
def test_binary_log_score_uses_probability_of_actual_outcome(
    prediction,
    ground_truth,
):
    assert calculate_log_score(
        prediction,
        ground_truth,
        0.98,
        QuestionType.BINARY,
    ) == pytest.approx(-0.0202027)


def test_mcq_accuracy_normalizes_json_scalar_ground_truth():
    assert calculate_accuracy(
        "Duke",
        '"Duke"',
        QuestionType.MCQ,
    ) == 1.0


def test_binary_accuracy_maps_bool_to_named_two_option_market():
    options = ["Slovakia", "Finland"]

    assert (
        calculate_accuracy(
            False,
            '"Finland"',
            QuestionType.BINARY,
            options=options,
        )
        == 1.0
    )


def test_binary_scores_named_two_option_market_with_options():
    options = ["Garcia", "Barrios"]

    assert calculate_brier_score(
        True,
        '"Garcia"',
        0.98,
        QuestionType.BINARY,
        options=options,
    ) == pytest.approx(0.0004)
    assert calculate_log_score(
        True,
        '"Garcia"',
        0.98,
        QuestionType.BINARY,
        options=options,
    ) == pytest.approx(-0.0202027)
