"""Record reviewed terminal event-validation failures for human adjudication."""

import argparse
from pathlib import Path
from typing import List, Tuple

from src.core.database import GenericDatabase
from src.domain.models import Article, Event
from src.services.evidence_quality.service import EvidenceQualityService


def _load_pairs(path: Path) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        if "::" not in value:
            raise ValueError(f"Invalid pair {value!r}; expected event_id::article_id")
        pairs.append(tuple(value.split("::", 1)))
    if len(pairs) != len(set(pairs)):
        raise ValueError("Selection contains duplicate event-source pairs")
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--selection-file", type=Path, required=True)
    parser.add_argument("--reason-code", required=True)
    parser.add_argument("--notes", required=True)
    args = parser.parse_args()

    db = GenericDatabase(str(args.db))
    service = EvidenceQualityService(db, args.version)
    recorded = 0
    for event_id, article_id in _load_pairs(args.selection_file):
        event = db.get(Event, event_id)
        article = db.get(Article, article_id)
        if event is None or article is None:
            raise ValueError(f"Unknown event-source pair: {event_id}::{article_id}")
        cited_ids = {event.source_article_id, *event.article_ids}
        if article_id not in cited_ids:
            raise ValueError(
                f"Article is not cited by event: {event_id}::{article_id}"
            )
        service.record_terminal_validation_deferral(
            event,
            article,
            reason_code=args.reason_code,
            notes=args.notes,
        )
        recorded += 1
    print(f"Recorded {recorded} terminal validation deferral(s).")


if __name__ == "__main__":
    main()
