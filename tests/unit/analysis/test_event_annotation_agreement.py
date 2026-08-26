from scripts.analysis.analyze_event_annotation_agreement import (
    binary_agreement_details,
    bootstrap_kappa_interval,
    classification_summary,
    cohen_kappa,
    collapse_date,
)


def test_cohen_kappa_for_partial_agreement() -> None:
    result = cohen_kappa(["a", "a", "b", "b"], ["a", "b", "b", "b"])

    assert result is not None
    assert round(result, 3) == 0.5


def test_bootstrap_kappa_interval_is_deterministic() -> None:
    first = bootstrap_kappa_interval(
        ["a", "a", "b", "b"], ["a", "b", "b", "b"], iterations=100
    )
    second = bootstrap_kappa_interval(
        ["a", "a", "b", "b"], ["a", "b", "b", "b"], iterations=100
    )

    assert first == second


def test_date_collapse_matches_tolerance_policy() -> None:
    assert collapse_date("correct") == "supported"
    assert collapse_date("near_match") == "supported"
    assert collapse_date("incorrect") == "not_supported"
    assert collapse_date("unclear") == "not_supported"


def test_binary_agreement_details_separates_positive_and_negative_agreement() -> None:
    result = binary_agreement_details(
        ["pass", "pass", "fail", "fail"],
        ["pass", "fail", "fail", "fail"],
        "pass",
    )

    assert round(result["positive_agreement"], 3) == 0.667
    assert round(result["negative_agreement"], 3) == 0.8
    assert result["pabak"] == 0.5


def test_classification_summary_reports_confusion_and_macro_f1() -> None:
    result = classification_summary(
        ["pass", "pass", "fail", "fail"],
        ["pass", "fail", "fail", "fail"],
    )

    assert result["n"] == 4
    assert result["accuracy"] == 0.75
    assert result["confusion"]["pass"]["fail"] == 1
    assert round(result["macro_f1"], 3) == 0.733
