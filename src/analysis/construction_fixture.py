"""Deterministic migration-fixture selection and evidence-pipeline analysis."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


SELECTION_VERSION = "construction-migration-fixture-v1"
DIMENSION_WEIGHTS = {
    "domain": 2.0,
    "question_type": 2.0,
    "source": 1.5,
    "evidence_tier": 1.0,
    "horizon_tier": 1.0,
    "difficulty": 0.5,
}


def _json_list(value: Optional[str]) -> List[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _json_dict(value: Optional[str]) -> Dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def stable_ids_hash(question_ids: Iterable[str]) -> str:
    """Hash a question-ID set in stable lexical order."""
    payload = "\n".join(sorted(set(question_ids))).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class QuestionProfile:
    """Selection metadata and legacy evidence-pipeline measurements."""

    question_id: str
    question_text: str
    source: str
    question_type: str
    domain: str
    difficulty: int
    resolution_date: str
    horizon_days: Optional[float]
    article_count: int
    source_count: int
    event_count: int
    outcome_count: int
    edge_count: int
    impact_count: int
    unsupported_event_count: int
    disconnected_event_count: int
    graph_depth: int
    graph_has_cycle: bool
    evidence_tier: str = ""
    horizon_tier: str = ""

    def dimensions(self) -> Dict[str, str]:
        return {
            "domain": self.domain,
            "question_type": self.question_type,
            "source": self.source,
            "evidence_tier": self.evidence_tier,
            "horizon_tier": self.horizon_tier,
            "difficulty": str(self.difficulty),
        }


def _graph_measurements(
    event_ids: Set[str],
    outcome_ids: Set[str],
    edges: Sequence[Tuple[str, str]],
) -> Tuple[int, bool, int]:
    """Return graph depth, cycle state, and non-outcome disconnection count."""
    nodes = set(event_ids) | set(outcome_ids)
    adjacency: Dict[str, Set[str]] = defaultdict(set)
    indegree = {node_id: 0 for node_id in nodes}
    reverse: Dict[str, Set[str]] = defaultdict(set)
    for source_id, target_id in edges:
        if source_id not in nodes or target_id not in nodes:
            continue
        if target_id not in adjacency[source_id]:
            adjacency[source_id].add(target_id)
            reverse[target_id].add(source_id)
            indegree[target_id] += 1

    queue = deque(
        sorted(node_id for node_id, degree in indegree.items() if degree == 0)
    )
    depth = {node_id: 1 for node_id in queue}
    visited = 0
    while queue:
        node_id = queue.popleft()
        visited += 1
        for target_id in sorted(adjacency[node_id]):
            depth[target_id] = max(depth.get(target_id, 1), depth[node_id] + 1)
            indegree[target_id] -= 1
            if indegree[target_id] == 0:
                queue.append(target_id)
    has_cycle = visited != len(nodes)
    graph_depth = 0 if not nodes else max(depth.values(), default=1)

    reaches_outcome = set(outcome_ids)
    pending = deque(sorted(outcome_ids))
    while pending:
        target_id = pending.popleft()
        for source_id in reverse[target_id]:
            if source_id not in reaches_outcome:
                reaches_outcome.add(source_id)
                pending.append(source_id)
    disconnected = len(set(event_ids) - reaches_outcome)
    return graph_depth, has_cycle, disconnected


def load_question_profiles(
    db_path: Path,
    candidate_ids: Sequence[str],
) -> List[QuestionProfile]:
    """Load immutable metadata and legacy evidence measurements for candidates."""
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    try:
        candidate_set = set(candidate_ids)
        questions = {
            row["id"]: row
            for row in connection.execute("SELECT * FROM questions")
            if row["id"] in candidate_set
        }
        missing = candidate_set - set(questions)
        if missing:
            missing_sample = sorted(missing)[:5]
            raise ValueError(f"Candidate IDs absent from database: {missing_sample}")

        direct_articles: Dict[str, Set[str]] = defaultdict(set)
        articles_by_id: Dict[str, sqlite3.Row] = {}
        for row in connection.execute(
            "SELECT id, source, collected_for_question_id FROM articles"
        ):
            articles_by_id[row["id"]] = row
            question_id = row["collected_for_question_id"]
            if question_id in candidate_set:
                direct_articles[question_id].add(row["id"])

        events_by_question: Dict[str, List[sqlite3.Row]] = defaultdict(list)
        for row in connection.execute(
            "SELECT id, article_ids, extracted_for_question_id, is_outcome FROM events"
        ):
            question_id = row["extracted_for_question_id"]
            if question_id in candidate_set:
                events_by_question[question_id].append(row)

        hypotheses_by_question: Dict[str, List[sqlite3.Row]] = defaultdict(list)
        for row in connection.execute(
            "SELECT source_event_id, target_event_id, evidence_article_ids, "
            "discovered_by_question_ids FROM causal_hypotheses"
        ):
            for question_id in _json_list(row["discovered_by_question_ids"]):
                if question_id in candidate_set:
                    hypotheses_by_question[question_id].append(row)

        impacts_by_question: Dict[str, List[sqlite3.Row]] = defaultdict(list)
        for row in connection.execute(
            "SELECT event_id, outcome_event_id, evidence_article_ids, question_id "
            "FROM event_outcome_impacts"
        ):
            question_id = row["question_id"]
            if question_id in candidate_set:
                impacts_by_question[question_id].append(row)

        profiles = []
        for question_id in sorted(candidate_set):
            question = questions[question_id]
            events = events_by_question[question_id]
            outcome_ids = {row["id"] for row in events if bool(row["is_outcome"])}
            event_ids = {row["id"] for row in events if not bool(row["is_outcome"])}
            hypotheses = hypotheses_by_question[question_id]
            impacts = impacts_by_question[question_id]
            edges = [
                (row["source_event_id"], row["target_event_id"])
                for row in hypotheses
            ]
            topology_edges = edges + [
                (row["event_id"], row["outcome_event_id"])
                for row in impacts
            ]
            graph_depth, has_cycle, disconnected = _graph_measurements(
                event_ids,
                outcome_ids,
                topology_edges,
            )

            article_ids = set(direct_articles[question_id])
            supported_event_ids = set()
            for event in events:
                linked = set(_json_list(event["article_ids"]))
                article_ids.update(linked)
                if linked and not bool(event["is_outcome"]):
                    supported_event_ids.add(event["id"])
            for edge in hypotheses:
                article_ids.update(_json_list(edge["evidence_article_ids"]))
            for impact in impacts:
                article_ids.update(_json_list(impact["evidence_article_ids"]))

            sources = {
                str(articles_by_id[article_id]["source"] or "unknown")
                for article_id in article_ids
                if article_id in articles_by_id
            }
            start = _parse_datetime(question["estimated_start_time"])
            resolution = _parse_datetime(question["resolution_date"])
            horizon_days = None
            if start and resolution:
                horizon_days = max(0.0, (resolution - start).total_seconds() / 86400)

            profiles.append(
                QuestionProfile(
                    question_id=question_id,
                    question_text=question["question_text"],
                    source=question["source"],
                    question_type=question["question_type"],
                    domain=question["domain"],
                    difficulty=int(question["difficulty"]),
                    resolution_date=question["resolution_date"],
                    horizon_days=horizon_days,
                    article_count=len(article_ids),
                    source_count=len(sources),
                    event_count=len(event_ids),
                    outcome_count=len(outcome_ids),
                    edge_count=len(hypotheses),
                    impact_count=len(impacts),
                    unsupported_event_count=len(event_ids - supported_event_ids),
                    disconnected_event_count=disconnected,
                    graph_depth=graph_depth,
                    graph_has_cycle=has_cycle,
                )
            )
        return _assign_numeric_tiers(profiles)
    finally:
        connection.close()


def _quartile_labels(values: Sequence[Optional[float]]) -> List[str]:
    indexed = sorted(
        ((value, index) for index, value in enumerate(values) if value is not None),
        key=lambda item: (item[0], item[1]),
    )
    labels = ["missing"] * len(values)
    count = len(indexed)
    for rank, (_, index) in enumerate(indexed):
        labels[index] = f"q{min(4, math.floor(rank * 4 / max(1, count)) + 1)}"
    return labels


def _assign_numeric_tiers(profiles: Sequence[QuestionProfile]) -> List[QuestionProfile]:
    article_tiers = _quartile_labels([float(item.article_count) for item in profiles])
    horizon_tiers = _quartile_labels([item.horizon_days for item in profiles])
    output = []
    for profile, article_tier, horizon_tier in zip(
        profiles,
        article_tiers,
        horizon_tiers,
    ):
        values = asdict(profile)
        values["evidence_tier"] = article_tier
        values["horizon_tier"] = horizon_tier
        output.append(QuestionProfile(**values))
    return output


def _proportional_targets(values: Sequence[str], size: int) -> Dict[str, int]:
    counts = Counter(values)
    categories = sorted(counts)
    if size < len(categories):
        raise ValueError("Fixture is too small to represent every category")
    targets = {category: 1 for category in categories}
    remaining = size - len(categories)
    expected_extra = {
        category: max(0.0, size * counts[category] / len(values) - 1)
        for category in categories
    }
    total_extra = sum(expected_extra.values())
    if remaining and total_extra:
        raw = {
            category: remaining * expected_extra[category] / total_extra
            for category in categories
        }
        for category in categories:
            targets[category] += math.floor(raw[category])
        unassigned = size - sum(targets.values())
        order = sorted(
            categories,
            key=lambda category: (
                -(raw[category] - math.floor(raw[category])),
                category,
            ),
        )
        for category in order[:unassigned]:
            targets[category] += 1
    return targets


def build_targets(
    profiles: Sequence[QuestionProfile],
    size: int,
) -> Dict[str, Dict[str, int]]:
    """Build proportional targets while retaining every observed category."""
    targets: Dict[str, Dict[str, int]] = {}
    for dimension in DIMENSION_WEIGHTS:
        values = [profile.dimensions()[dimension] for profile in profiles]
        targets[dimension] = _proportional_targets(values, size)
    return targets


def selection_counts(
    profiles: Sequence[QuestionProfile],
) -> Dict[str, Dict[str, int]]:
    counts: Dict[str, Counter[str]] = {
        dimension: Counter() for dimension in DIMENSION_WEIGHTS
    }
    for profile in profiles:
        for dimension, value in profile.dimensions().items():
            counts[dimension][value] += 1
    return {
        dimension: dict(sorted(dimension_counts.items()))
        for dimension, dimension_counts in counts.items()
    }


def _selection_objective(
    profiles: Sequence[QuestionProfile],
    targets: Dict[str, Dict[str, int]],
) -> float:
    actual = selection_counts(profiles)
    score = 0.0
    for dimension, dimension_targets in targets.items():
        for value, target in dimension_targets.items():
            difference = actual[dimension].get(value, 0) - target
            score += DIMENSION_WEIGHTS[dimension] * (difference / max(1, target)) ** 2
    return score


def select_fixture(
    profiles: Sequence[QuestionProfile],
    size: int = 20,
    seed: str = SELECTION_VERSION,
    starts: int = 32,
) -> Tuple[List[QuestionProfile], Dict[str, Dict[str, int]], float]:
    """Select a stable, balanced fixture using deterministic swap optimization."""
    if size > len(profiles):
        raise ValueError("Fixture size exceeds candidate count")
    targets = build_targets(profiles, size)
    profile_map = {profile.question_id: profile for profile in profiles}
    all_ids = set(profile_map)
    best_ids: Optional[Set[str]] = None
    best_score = math.inf

    for start in range(starts):
        ordered = sorted(
            profiles,
            key=lambda profile: hashlib.sha256(
                f"{seed}:{start}:{profile.question_id}".encode("utf-8")
            ).hexdigest(),
        )
        selected_ids = {profile.question_id for profile in ordered[:size]}
        score = _selection_objective(
            [profile_map[question_id] for question_id in selected_ids],
            targets,
        )
        while True:
            best_swap: Optional[Tuple[str, str]] = None
            swap_score = score
            for outgoing in sorted(selected_ids):
                for incoming in sorted(all_ids - selected_ids):
                    candidate_ids = (selected_ids - {outgoing}) | {incoming}
                    candidate_score = _selection_objective(
                        [profile_map[question_id] for question_id in candidate_ids],
                        targets,
                    )
                    if candidate_score < swap_score - 1e-12:
                        swap_score = candidate_score
                        best_swap = (outgoing, incoming)
            if best_swap is None:
                break
            selected_ids.remove(best_swap[0])
            selected_ids.add(best_swap[1])
            score = swap_score
        lexical_ids = sorted(selected_ids)
        if score < best_score - 1e-12 or (
            abs(score - best_score) <= 1e-12
            and (best_ids is None or lexical_ids < sorted(best_ids))
        ):
            best_ids = selected_ids
            best_score = score

    assert best_ids is not None
    selected = [profile_map[question_id] for question_id in sorted(best_ids)]
    return selected, targets, best_score


def load_quality_summary(
    quality_db_path: Path,
    profiles: Sequence[QuestionProfile],
) -> Dict[str, Dict[str, int]]:
    """Summarize v2 quality states for each fixture question's evidence set."""
    question_ids = [profile.question_id for profile in profiles]
    question_id_set = set(question_ids)
    connection = sqlite3.connect(str(quality_db_path))
    connection.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in question_ids)
        evidence_ids: Dict[str, Set[str]] = defaultdict(set)
        for row in connection.execute(
            f"SELECT id, collected_for_question_id FROM articles "
            f"WHERE collected_for_question_id IN ({placeholders})",
            question_ids,
        ):
            evidence_ids[row["collected_for_question_id"]].add(row["id"])
        for row in connection.execute(
            f"SELECT extracted_for_question_id, article_ids FROM events "
            f"WHERE extracted_for_question_id IN ({placeholders})",
            question_ids,
        ):
            evidence_ids[row["extracted_for_question_id"]].update(
                _json_list(row["article_ids"])
            )
        for row in connection.execute(
            "SELECT evidence_article_ids, discovered_by_question_ids "
            "FROM causal_hypotheses"
        ):
            for question_id in _json_list(row["discovered_by_question_ids"]):
                if question_id in question_id_set:
                    evidence_ids[question_id].update(
                        _json_list(row["evidence_article_ids"])
                    )
        for row in connection.execute(
            f"SELECT question_id, evidence_article_ids FROM event_outcome_impacts "
            f"WHERE question_id IN ({placeholders})",
            question_ids,
        ):
            evidence_ids[row["question_id"]].update(
                _json_list(row["evidence_article_ids"])
            )

        records = {
            row["article_id"]: row
            for row in connection.execute(
                "SELECT article_id, status, flags, clean_markdown, metadata "
                "FROM article_quality_records"
            )
        }
        summaries: Dict[str, Dict[str, int]] = {}
        for question_id in question_ids:
            counts = Counter(
                {
                    "evidence_articles": len(evidence_ids[question_id]),
                    "quality_records": 0,
                    "complete": 0,
                    "needs_repair": 0,
                    "clean_markdown": 0,
                    "valid": 0,
                    "invalid": 0,
                    "defer": 0,
                    "unlabelled": 0,
                }
            )
            for article_id in evidence_ids[question_id]:
                record = records.get(article_id)
                if record is None:
                    continue
                counts["quality_records"] += 1
                counts[str(record["status"])] += 1
                if record["clean_markdown"]:
                    counts["clean_markdown"] += 1
                validity = _json_dict(record["metadata"]).get(
                    "cleaner_validity",
                    {},
                ).get("article_validity")
                if validity in {"valid", "invalid", "defer"}:
                    counts[validity] += 1
                else:
                    counts["unlabelled"] += 1
            summaries[question_id] = dict(counts)
        return summaries
    finally:
        connection.close()


def profiles_summary(profiles: Sequence[QuestionProfile]) -> Dict[str, Any]:
    """Return aggregate baseline measurements for a profile collection."""
    if not profiles:
        return {}

    def numeric(field: str) -> Dict[str, float]:
        values = sorted(float(getattr(profile, field)) for profile in profiles)
        middle = len(values) // 2
        median = (
            values[middle]
            if len(values) % 2
            else (values[middle - 1] + values[middle]) / 2
        )
        return {
            "min": values[0],
            "median": median,
            "max": values[-1],
            "total": sum(values),
        }

    return {
        "questions": len(profiles),
        "dimensions": selection_counts(profiles),
        "articles": numeric("article_count"),
        "sources": numeric("source_count"),
        "events": numeric("event_count"),
        "edges": numeric("edge_count"),
        "impacts": numeric("impact_count"),
        "graph_depth": numeric("graph_depth"),
        "questions_with_cycles": sum(profile.graph_has_cycle for profile in profiles),
        "questions_with_unsupported_events": sum(
            profile.unsupported_event_count > 0 for profile in profiles
        ),
        "questions_with_disconnected_events": sum(
            profile.disconnected_event_count > 0 for profile in profiles
        ),
    }
