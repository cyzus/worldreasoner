"""Analyze blinded event-source annotations and model verification labels.

The model comparison uses only labels on which the two human annotators agree.
Date labels are additionally collapsed to "supported within tolerance" for
compatibility with historical verifier runs that predate ``near_match``.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence


def cohen_kappa(left: Sequence[str], right: Sequence[str]) -> Optional[float]:
    """Return unweighted Cohen's kappa, or None when chance agreement is 1."""
    if len(left) != len(right):
        raise ValueError("Label sequences must have the same length")
    if not left:
        return None
    observed = sum(a == b for a, b in zip(left, right)) / len(left)
    left_counts = Counter(left)
    right_counts = Counter(right)
    expected = sum(
        left_counts[label] * right_counts[label] for label in set(left) | set(right)
    ) / (len(left) ** 2)
    if expected == 1.0:
        return None
    return (observed - expected) / (1.0 - expected)


def bootstrap_kappa_interval(
    left: Sequence[str],
    right: Sequence[str],
    iterations: int = 5000,
    seed: int = 20261004,
) -> Optional[List[float]]:
    """Return a deterministic pair-bootstrap 95% interval for kappa."""
    if len(left) != len(right):
        raise ValueError("Label sequences must have the same length")
    if not left:
        return None
    rng = random.Random(seed)
    estimates: List[float] = []
    for _ in range(iterations):
        indices = [rng.randrange(len(left)) for _ in left]
        estimate = cohen_kappa(
            [left[index] for index in indices],
            [right[index] for index in indices],
        )
        if estimate is not None:
            estimates.append(estimate)
    if not estimates:
        return None
    estimates.sort()
    lower = estimates[int(0.025 * (len(estimates) - 1))]
    upper = estimates[int(0.975 * (len(estimates) - 1))]
    return [lower, upper]


def binary_agreement_details(
    left: Sequence[str], right: Sequence[str], positive_label: str
) -> Dict[str, float]:
    """Return prevalence-aware agreement details for a binary decision."""
    both_positive = sum(
        a == positive_label and b == positive_label for a, b in zip(left, right)
    )
    left_only = sum(
        a == positive_label and b != positive_label for a, b in zip(left, right)
    )
    right_only = sum(
        a != positive_label and b == positive_label for a, b in zip(left, right)
    )
    both_negative = len(left) - both_positive - left_only - right_only
    positive_denominator = 2 * both_positive + left_only + right_only
    negative_denominator = 2 * both_negative + left_only + right_only
    return {
        "both_positive": both_positive,
        "left_positive_only": left_only,
        "right_positive_only": right_only,
        "both_negative": both_negative,
        "positive_agreement": (
            2 * both_positive / positive_denominator
            if positive_denominator
            else 0.0
        ),
        "negative_agreement": (
            2 * both_negative / negative_denominator
            if negative_denominator
            else 0.0
        ),
        "prevalence_index": abs(both_positive - both_negative) / len(left),
        "bias_index": abs(left_only - right_only) / len(left),
        "pabak": 2 * (both_positive + both_negative) / len(left) - 1,
    }


def classification_summary(
    reference: Sequence[str], prediction: Sequence[str]
) -> Dict[str, object]:
    """Compute accuracy, macro-F1, and a compact confusion matrix."""
    if len(reference) != len(prediction):
        raise ValueError("Reference and prediction lengths must match")
    labels = sorted(set(reference) | set(prediction))
    confusion = {
        label: {predicted: 0 for predicted in labels} for label in labels
    }
    for expected, actual in zip(reference, prediction):
        confusion[expected][actual] += 1

    per_class: Dict[str, Dict[str, float]] = {}
    for label in labels:
        true_positive = confusion[label][label]
        false_positive = sum(
            confusion[other][label] for other in labels if other != label
        )
        false_negative = sum(
            confusion[label][other] for other in labels if other != label
        )
        precision = (
            true_positive / (true_positive + false_positive)
            if true_positive + false_positive
            else 0.0
        )
        recall = (
            true_positive / (true_positive + false_negative)
            if true_positive + false_negative
            else 0.0
        )
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0
        )
        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": sum(confusion[label].values()),
        }

    count = len(reference)
    accuracy = (
        sum(expected == actual for expected, actual in zip(reference, prediction))
        / count
        if count
        else 0.0
    )
    macro_f1 = (
        sum(values["f1"] for values in per_class.values()) / len(per_class)
        if per_class
        else 0.0
    )
    return {
        "n": count,
        "accuracy": accuracy,
        "macro_f1": macro_f1,
        "labels": labels,
        "per_class": per_class,
        "confusion": confusion,
    }


def collapse_date(label: str) -> str:
    """Map human and model date labels onto the shared tolerance policy."""
    if label in {"correct", "near_match"}:
        return "supported"
    if label in {"incorrect", "unclear"}:
        return "not_supported"
    raise ValueError(f"Unknown date label: {label}")


def _read_annotations(path: Path) -> Dict[str, Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    indexed = {row["item_id"]: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError(f"Duplicate item IDs in {path}")
    return indexed


def _load_model_labels(
    db_path: Path,
    dataset_version: str,
    started_at: str,
    finished_at: str,
) -> Dict[str, Dict[str, str]]:
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT event_id, article_id, support, date_validity, entity_match, "
            "action, confidence, model, created_at "
            "FROM event_evidence_verifications "
            "WHERE dataset_version = ? AND created_at >= ? AND created_at <= ? "
            "ORDER BY created_at, id",
            (dataset_version, started_at, finished_at),
        ).fetchall()
    finally:
        connection.close()
    return {f'{row["event_id"]}::{row["article_id"]}': dict(row) for row in rows}


def _agreement(
    first: Dict[str, Dict[str, str]],
    second: Dict[str, Dict[str, str]],
    field: str,
    normalize: Callable[[str], str] = lambda value: value,
    positive_label: Optional[str] = None,
) -> Dict[str, object]:
    item_ids = sorted(first)
    left = [normalize(first[item_id][field]) for item_id in item_ids]
    right = [normalize(second[item_id][field]) for item_id in item_ids]
    observed = sum(a == b for a, b in zip(left, right)) / len(left)
    left_counts = Counter(left)
    right_counts = Counter(right)
    expected = sum(
        left_counts[label] * right_counts[label]
        for label in set(left) | set(right)
    ) / (len(left) ** 2)
    result: Dict[str, object] = {
        "n": len(item_ids),
        "observed_agreement": observed,
        "expected_agreement": expected,
        "cohen_kappa": cohen_kappa(left, right),
        "cohen_kappa_bootstrap_95ci": bootstrap_kappa_interval(left, right),
        "first_distribution": dict(Counter(left)),
        "second_distribution": dict(Counter(right)),
        "confusion": classification_summary(left, right)["confusion"],
    }
    if positive_label is not None:
        result["binary_details"] = binary_agreement_details(
            left, right, positive_label
        )
    return result


def _row_agreement(
    first: Dict[str, Dict[str, str]],
    second: Dict[str, Dict[str, str]],
    transform: Callable[[Dict[str, str]], str],
    positive_label: str,
) -> Dict[str, object]:
    item_ids = sorted(first)
    left = [transform(first[item_id]) for item_id in item_ids]
    right = [transform(second[item_id]) for item_id in item_ids]
    observed = sum(a == b for a, b in zip(left, right)) / len(left)
    left_counts = Counter(left)
    right_counts = Counter(right)
    expected = sum(
        left_counts[label] * right_counts[label]
        for label in set(left) | set(right)
    ) / (len(left) ** 2)
    return {
        "n": len(item_ids),
        "observed_agreement": observed,
        "expected_agreement": expected,
        "cohen_kappa": cohen_kappa(left, right),
        "cohen_kappa_bootstrap_95ci": bootstrap_kappa_interval(left, right),
        "first_distribution": dict(left_counts),
        "second_distribution": dict(right_counts),
        "confusion": classification_summary(left, right)["confusion"],
        "binary_details": binary_agreement_details(left, right, positive_label),
    }


def _model_consensus_comparison(
    first: Dict[str, Dict[str, str]],
    second: Dict[str, Dict[str, str]],
    model: Dict[str, Dict[str, str]],
    human_field: str,
    model_field: str,
    normalize: Callable[[str], str] = lambda value: value,
) -> Dict[str, object]:
    reference: List[str] = []
    prediction: List[str] = []
    for item_id in sorted(first):
        if item_id not in model:
            continue
        left = normalize(first[item_id][human_field])
        right = normalize(second[item_id][human_field])
        if left != right:
            continue
        reference.append(left)
        prediction.append(normalize(model[item_id][model_field]))
    return classification_summary(reference, prediction)


def _human_gate(row: Dict[str, str]) -> str:
    valid = (
        row["source_support"] == "full"
        and collapse_date(row["date_validity"]) == "supported"
        and row["entity_match"] == "correct"
    )
    return "pass" if valid else "fail"


def _model_gate(row: Dict[str, str]) -> str:
    valid = (
        row["support"] == "full"
        and collapse_date(row["date_validity"]) == "supported"
        and row["entity_match"] == "correct"
    )
    return "pass" if valid else "fail"


def analyze(
    first_path: Path,
    second_path: Path,
    db_path: Path,
    model_run_path: Path,
) -> Dict[str, object]:
    first = _read_annotations(first_path)
    second = _read_annotations(second_path)
    if set(first) != set(second):
        raise ValueError("Annotation submissions do not contain identical item IDs")

    model_run = json.loads(model_run_path.read_text(encoding="utf-8"))
    model = _load_model_labels(
        db_path,
        model_run["dataset_version"],
        model_run["started_at"],
        model_run["finished_at"],
    )
    missing_model = sorted(set(first) - set(model))

    human_agreement = {
        "source_support": _agreement(first, second, "source_support"),
        "source_supported_or_partial": _agreement(
            first,
            second,
            "source_support",
            lambda label: (
                "supported" if label in {"full", "partial"} else "not_supported"
            ),
            "supported",
        ),
        "source_strictly_full": _agreement(
            first,
            second,
            "source_support",
            lambda label: "full" if label == "full" else "not_full",
            "full",
        ),
        "date_validity_exact": _agreement(first, second, "date_validity"),
        "date_supported_within_tolerance": _agreement(
            first, second, "date_validity", collapse_date, "supported"
        ),
        "entity_match": _agreement(first, second, "entity_match"),
        "entity_correct": _agreement(
            first,
            second,
            "entity_match",
            lambda label: "correct" if label == "correct" else "not_correct",
            "correct",
        ),
        "conservative_validity_gate": _row_agreement(
            first, second, _human_gate, "pass"
        ),
    }
    model_comparison = {
        "source_support": _model_consensus_comparison(
            first, second, model, "source_support", "support"
        ),
        "date_supported_within_tolerance": _model_consensus_comparison(
            first,
            second,
            model,
            "date_validity",
            "date_validity",
            collapse_date,
        ),
        "entity_match": _model_consensus_comparison(
            first, second, model, "entity_match", "entity_match"
        ),
    }

    gate_reference: List[str] = []
    gate_prediction: List[str] = []
    for item_id in sorted(first):
        if item_id not in model:
            continue
        left = _human_gate(first[item_id])
        right = _human_gate(second[item_id])
        if left != right:
            continue
        gate_reference.append(left)
        gate_prediction.append(_model_gate(model[item_id]))
    model_comparison["conservative_validity_gate"] = classification_summary(
        gate_reference, gate_prediction
    )

    annotators = [
        sorted({row["annotator_id"] for row in submission.values()})
        for submission in (first, second)
    ]
    return {
        "artifact": "event-annotation-agreement-analysis",
        "packet_id": next(iter(first.values()))["packet_id"],
        "annotators": annotators,
        "items": len(first),
        "model_labels_found": len(set(first) & set(model)),
        "missing_model_item_ids": missing_model,
        "sampling_note": (
            "The overlap pilot was stratified by domain and automated action; "
            "model metrics are calibration diagnostics, not prevalence estimates."
        ),
        "date_comparison_policy": {
            "supported": ["correct", "near_match"],
            "not_supported": ["incorrect", "unclear"],
            "reason": (
                "Historical verifier output may predate the near_match label."
            ),
        },
        "human_agreement": human_agreement,
        "model_vs_human_consensus": model_comparison,
        "model_action_distribution": dict(
            Counter(row["action"] for item_id, row in model.items() if item_id in first)
        ),
    }


def _percent(value: float) -> str:
    return f"{100 * value:.1f}%"


def render_markdown(report: Dict[str, object]) -> str:
    lines = [
        "# Event-Source Annotation Agreement",
        "",
        f"- Items: {report['items']}",
        f"- Model labels found: {report['model_labels_found']}",
        "- Model comparisons use only human-consensus items.",
        "- Date comparison collapses correct/near-match into supported within tolerance.",
        f"- {report['sampling_note']}",
        "",
        "## Human-Human Agreement",
        "",
        "| Axis | N | Agreement | Cohen's kappa | Bootstrap 95% CI |",
        "|---|---:|---:|---:|---:|",
    ]
    for axis, values in report["human_agreement"].items():
        kappa = values["cohen_kappa"]
        kappa_text = f"{kappa:.3f}" if kappa is not None else "N/A"
        interval = values["cohen_kappa_bootstrap_95ci"]
        interval_text = (
            f"[{interval[0]:.3f}, {interval[1]:.3f}]" if interval else "N/A"
        )
        lines.append(
            f"| {axis.replace('_', ' ')} | {values['n']} | "
            f"{_percent(values['observed_agreement'])} | "
            f"{kappa_text} | {interval_text} |"
        )

    lines.extend(
        [
            "",
            "## Model vs Human Consensus",
            "",
            "| Axis | Consensus N | Accuracy | Macro-F1 |",
            "|---|---:|---:|---:|",
        ]
    )
    for axis, values in report["model_vs_human_consensus"].items():
        lines.append(
            f"| {axis.replace('_', ' ')} | {values['n']} | "
            f"{_percent(values['accuracy'])} | {values['macro_f1']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Model Action Distribution",
            "",
        ]
    )
    for action, count in sorted(report["model_action_distribution"].items()):
        lines.append(f"- `{action}`: {count}")
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", type=Path, required=True)
    parser.add_argument("--second", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--model-run", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = analyze(args.first, args.second, args.db, args.model_run)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    args.markdown_output.write_text(render_markdown(report), encoding="utf-8")


if __name__ == "__main__":
    main()
