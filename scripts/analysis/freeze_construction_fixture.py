"""Freeze and report the 20-question construction migration fixture.

The committed manifest contains question metadata and aggregate measurements,
never article bodies. The source database remains a local versioned artifact.

Usage:
    uv run --no-sync python scripts/analysis/freeze_construction_fixture.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analysis.construction_fixture import (  # noqa: E402
    SELECTION_VERSION,
    QuestionProfile,
    load_quality_summary,
    load_question_profiles,
    profiles_summary,
    select_fixture,
    selection_counts,
    stable_ids_hash,
)


DEFAULT_DB = ROOT / "data" / "versions" / "v1" / "worldreasoner.db"
DEFAULT_QUALITY_DB = ROOT / "data" / "versions" / "v2_0" / "worldreasoner.db"
DEFAULT_CANDIDATES = ROOT / "include_ids.txt"
DEFAULT_MANIFEST = (
    ROOT / "config" / "fixtures" / "construction_migration_20.json"
)
DEFAULT_REPORT = ROOT / "docs" / "construction_migration_fixture.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--quality-db", type=Path, default=DEFAULT_QUALITY_DB)
    parser.add_argument("--candidate-ids", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--size", type=int, default=20)
    parser.add_argument("--seed", default=SELECTION_VERSION)
    parser.add_argument("--manifest-output", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace an existing frozen manifest instead of verifying it.",
    )
    return parser.parse_args()


def load_ids(path: Path) -> List[str]:
    values = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    values = [value for value in values if value and not value.startswith("#")]
    if len(values) != len(set(values)):
        raise ValueError(f"Candidate ID file contains duplicates: {path}")
    return values


def load_source_manifest(db_path: Path) -> Dict[str, Any]:
    manifest_path = db_path.with_name("manifest.json")
    if not manifest_path.exists():
        return {}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def build_manifest(
    db_path: Path,
    candidate_path: Path,
    candidate_ids: Sequence[str],
    selected: Sequence[QuestionProfile],
    targets: Dict[str, Dict[str, int]],
    objective: float,
    quality_db_path: Optional[Path],
    quality: Dict[str, Dict[str, int]],
    seed: str,
) -> Dict[str, Any]:
    source_manifest = load_source_manifest(db_path)
    quality_manifest = load_source_manifest(quality_db_path) if quality_db_path else {}
    quality_totals: Dict[str, int] = {}
    for summary in quality.values():
        for key, value in summary.items():
            quality_totals[key] = quality_totals.get(key, 0) + value
    quality_totals["missing_quality_records"] = (
        quality_totals.get("evidence_articles", 0)
        - quality_totals.get("quality_records", 0)
    )
    return {
        "fixture_version": SELECTION_VERSION,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "selection": {
            "method": "deterministic multi-start swap optimization",
            "seed": seed,
            "candidate_file": str(candidate_path.relative_to(ROOT)),
            "candidate_count": len(candidate_ids),
            "candidate_ids_sha256": stable_ids_hash(candidate_ids),
            "fixture_size": len(selected),
            "targets": targets,
            "actual": selection_counts(selected),
            "objective": objective,
            "notes": [
                "Selection uses metadata and legacy evidence-volume tiers.",
                (
                    "It does not filter candidates by graph validity or v2 cleanup "
                    "outcome."
                ),
                "Question IDs are the frozen contract; database files remain local.",
            ],
        },
        "source": {
            "database": str(db_path.relative_to(ROOT)),
            "dataset_version": source_manifest.get("dataset_version"),
            "database_sha256": source_manifest.get("database_sha256"),
            "question_id_sha256": source_manifest.get("question_id_sha256"),
        },
        "quality_comparison": {
            "database": (
                str(quality_db_path.relative_to(ROOT)) if quality_db_path else None
            ),
            "dataset_version": quality_manifest.get("dataset_version"),
            "database_sha256": quality_manifest.get("database_sha256"),
            "manifest_updated_at": quality_manifest.get("updated_at"),
            "question_evidence_link_totals": quality_totals,
        },
        "question_ids": [profile.question_id for profile in selected],
        "profiles": [
            {
                **profile.__dict__,
                "quality_summary": quality.get(profile.question_id, {}),
            }
            for profile in selected
        ],
        "legacy_baseline": profiles_summary(selected),
    }


def _fmt_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else f"{value:.1f}"


def render_report(manifest: Dict[str, Any]) -> str:
    selection = manifest["selection"]
    baseline = manifest["legacy_baseline"]
    profiles = manifest["profiles"]
    lines = [
        "# Construction Migration Fixture",
        "",
        "## Purpose",
        "",
        "This fixture freezes 20 paper-facing questions for comparing the legacy",
        "evidence pipeline with `construction-v2`. It is a migration test set, not",
        "an estimate of benchmark performance. Selection balances source, answer",
        "type, domain, difficulty, forecast horizon, and legacy evidence volume.",
        "No article bodies are stored in the fixture manifest.",
        "",
        "## Reproduce",
        "",
        "```powershell",
        "uv run --no-sync python scripts/analysis/freeze_construction_fixture.py",
        "```",
        "",
        "Without `--replace`, the command verifies that deterministic selection",
        "still produces the frozen IDs and refuses to rewrite the manifest.",
        "",
        "## Frozen Contract",
        "",
        f"- Fixture version: `{manifest['fixture_version']}`",
        f"- Candidate questions: {selection['candidate_count']}",
        f"- Frozen questions: {selection['fixture_size']}",
        f"- Candidate ID hash: `{selection['candidate_ids_sha256']}`",
        f"- Source dataset: `{manifest['source']['dataset_version']}`",
        f"- Source database hash: `{manifest['source']['database_sha256']}`",
        "",
        "## Selection Balance",
        "",
        "| Dimension | Target | Actual |",
        "|---|---|---|",
    ]
    for dimension, targets in selection["targets"].items():
        actual = selection["actual"][dimension]
        lines.append(
            f"| {dimension} | `{json.dumps(targets, sort_keys=True)}` | "
            f"`{json.dumps(actual, sort_keys=True)}` |"
        )

    lines.extend(
        [
            "",
            "## Legacy Evidence Baseline",
            "",
            "The baseline describes existing persisted outputs. It does not assert",
            "that every article or graph element is valid; those are precisely the",
            "properties the refactored pipeline and v2 quality gates must improve.",
            "",
            "| Measure | Minimum | Median | Maximum | Total |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for label, key in (
        ("Evidence articles", "articles"),
        ("Publishers", "sources"),
        ("Non-outcome events", "events"),
        ("Causal edges", "edges"),
        ("Outcome impacts", "impacts"),
        ("Graph depth", "graph_depth"),
    ):
        values = baseline[key]
        lines.append(
            f"| {label} | {_fmt_number(values['min'])} | "
            f"{_fmt_number(values['median'])} | {_fmt_number(values['max'])} | "
            f"{_fmt_number(values['total'])} |"
        )
    lines.extend(
        [
            "",
            f"- Questions containing a directed cycle: "
            f"{baseline['questions_with_cycles']}",
            f"- Questions with at least one unsupported event: "
            f"{baseline['questions_with_unsupported_events']}",
            f"- Questions with at least one event disconnected from every outcome: "
            f"{baseline['questions_with_disconnected_events']}",
            "",
            "## v2 Evidence-Quality Comparison",
            "",
            "Counts below are question-evidence links, so an article used by two",
            "questions contributes twice. The v2 database is evolving; these values",
            "describe the manifest timestamp recorded in the frozen artifact.",
            "",
            "| Measure | Count |",
            "|---|---:|",
        ]
    )
    quality_totals = manifest["quality_comparison"][
        "question_evidence_link_totals"
    ]
    for label, key in (
        ("Evidence links", "evidence_articles"),
        ("Links with quality records", "quality_records"),
        ("Missing quality records", "missing_quality_records"),
        ("Complete", "complete"),
        ("Needs repair", "needs_repair"),
        ("Clean Markdown available", "clean_markdown"),
        ("LLM-valid", "valid"),
        ("LLM-invalid", "invalid"),
        ("Unlabelled by LLM", "unlabelled"),
    ):
        lines.append(f"| {label} | {quality_totals.get(key, 0)} |")
    lines.extend(
        [
            "",
            "## Per-Question Diagnostics",
            "",
            "| ID | Domain | Type | Source | Articles | Publishers | Events | Edges | "
            "Impacts | Depth | Unsupported | Disconnected | v2 complete/repair |",
            "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for profile in profiles:
        quality = profile.get("quality_summary", {})
        lines.append(
            f"| `{profile['question_id']}` | {profile['domain']} | "
            f"{profile['question_type']} | {profile['source']} | "
            f"{profile['article_count']} | {profile['source_count']} | "
            f"{profile['event_count']} | {profile['edge_count']} | "
            f"{profile['impact_count']} | {profile['graph_depth']} | "
            f"{profile['unsupported_event_count']} | "
            f"{profile['disconnected_event_count']} | "
            f"{quality.get('complete', 0)}/{quality.get('needs_repair', 0)} |"
        )
    lines.extend(
        [
            "",
            "## Required Parity Run",
            "",
            "Run the legacy and refactored hindsight-construction paths on the exact",
            "IDs above. Compare completion, retries, terminal failures, raw and",
            "approved evidence counts, publisher/date coverage, event support, graph",
            "validation, latency, tokens, and cost. Preserve per-question failures;",
            "an aggregate average must not hide questions that fail to complete.",
            "",
        ]
    )
    return "\n".join(lines)


def write_or_verify_manifest(
    output_path: Path,
    manifest: Dict[str, Any],
    replace: bool,
) -> Dict[str, Any]:
    if output_path.exists() and not replace:
        current = json.loads(output_path.read_text(encoding="utf-8"))
        if current.get("question_ids") != manifest.get("question_ids"):
            raise RuntimeError(
                "Deterministic selection differs from the frozen fixture. "
                "Inspect the change and use --replace only if intentional."
            )
        if current.get("selection", {}).get("candidate_ids_sha256") != manifest.get(
            "selection",
            {},
        ).get("candidate_ids_sha256"):
            raise RuntimeError(
                "The candidate question set changed after fixture freeze"
            )
        return current
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    args = parse_args()
    candidate_ids = load_ids(args.candidate_ids)
    profiles = load_question_profiles(args.db, candidate_ids)
    selected, targets, objective = select_fixture(
        profiles,
        size=args.size,
        seed=args.seed,
    )
    quality = (
        load_quality_summary(args.quality_db, selected)
        if args.quality_db and args.quality_db.exists()
        else {}
    )
    manifest = build_manifest(
        args.db,
        args.candidate_ids,
        candidate_ids,
        selected,
        targets,
        objective,
        args.quality_db,
        quality,
        args.seed,
    )
    manifest = write_or_verify_manifest(
        args.manifest_output,
        manifest,
        args.replace,
    )
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(render_report(manifest), encoding="utf-8")
    print(
        json.dumps(
            {
                "manifest": str(args.manifest_output),
                "report": str(args.report_output),
                "questions": len(selected),
                "question_ids_sha256": stable_ids_hash(
                    profile.question_id for profile in selected
                ),
                "objective": objective,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
