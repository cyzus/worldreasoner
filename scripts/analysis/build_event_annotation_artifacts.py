"""Build blinded event-source annotation packets from cleaned v2 evidence."""

import argparse
import csv
import hashlib
import json
import random
import sqlite3
from collections import defaultdict, deque
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from markdown_it import MarkdownIt

from src.core.database import GenericDatabase
from src.domain.models import (
    Article,
    ArticleQualityRecord,
    Event,
    EventEvidenceVerification,
    QualityStatus,
    Question,
)


ARTICLE_CSS = """
* { box-sizing: border-box; }
body { max-width: 850px; margin: 0 auto; padding: 26px 34px 80px; color: #202725;
background: #fff; font: 15px/1.68 Georgia, "Times New Roman", serif; letter-spacing: 0; }
h1,h2,h3,h4 { color: #17201e; font-family: Inter,system-ui,sans-serif;
line-height: 1.25; letter-spacing: 0; }
h1 { margin: 0 0 20px; font-size: 27px; } h2 { margin-top: 30px; font-size: 21px; }
h3 { margin-top: 24px; font-size: 18px; } p { margin: 0 0 15px; }
ul,ol { padding-left: 24px; } blockquote { margin: 20px 0; padding-left: 16px;
border-left: 4px solid #7db7ad; color: #4c5956; }
code { padding: 2px 4px; border-radius: 3px; background: #edf1ef;
font: .88em ui-monospace,monospace; } pre { overflow-x: auto; padding: 14px;
background: #edf1ef; } pre code { padding: 0; }
hr { margin: 26px 0; border: 0; border-top: 1px solid #d8dedc; }
.md-link { color: #087f70; text-decoration: underline; text-decoration-color: #a7ccc5; }
.image-alt { color: #69736f; font: 13px ui-sans-serif,system-ui,sans-serif; }
table { width: 100%; border-collapse: collapse;
font: 14px ui-sans-serif,system-ui,sans-serif; }
th,td { padding: 8px 10px; border: 1px solid #d8dedc; text-align: left; }
""".strip()


def _renderer() -> MarkdownIt:
    renderer = MarkdownIt(
        "commonmark",
        {"html": False, "linkify": False, "typographer": False},
    )
    renderer.renderer.rules["link_open"] = lambda *_args: '<span class="md-link">'
    renderer.renderer.rules["link_close"] = lambda *_args: "</span>"

    def render_image(tokens: list, index: int, *_args: object) -> str:
        return (
            '<span class="image-alt">[Image: '
            f"{escape(tokens[index].content or 'image')}]</span>"
        )

    renderer.renderer.rules["image"] = render_image
    return renderer


def _render_document(markdown: str, renderer: MarkdownIt) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<style>{ARTICLE_CSS}</style></head><body>"
        f"{renderer.render(markdown)}</body></html>"
    )


def _iso(value: Any) -> str:
    if value is None:
        return ""
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _ground_truth(question: Optional[Question]) -> str:
    if question is None or question.ground_truth is None:
        return ""
    value = question.ground_truth
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _article_ids(event: Event) -> Iterable[str]:
    seen = set()
    for article_id in [event.source_article_id, *event.article_ids]:
        if article_id and article_id not in seen:
            seen.add(article_id)
            yield article_id


def _candidate_rows(
    db: GenericDatabase,
    dataset_version: str,
) -> List[Dict[str, str]]:
    articles = {article.id: article for article in db.get_many(Article)}
    questions = {question.id: question for question in db.get_many(Question)}
    quality = {
        record.article_id: record
        for record in db.get_many(
            ArticleQualityRecord,
            filters={"dataset_version": dataset_version},
        )
        if record.status == QualityStatus.COMPLETE and record.clean_markdown
    }
    latest_verification = {}
    try:
        verifications = db.get_many(EventEvidenceVerification)
    except sqlite3.OperationalError as error:
        if "no such table" not in str(error):
            raise
        verifications = []
    for verification in verifications:
        if verification.dataset_version != dataset_version:
            continue
        key = (verification.event_id, verification.article_id)
        current = latest_verification.get(key)
        if current is None or verification.created_at > current.created_at:
            latest_verification[key] = verification

    rows: List[Dict[str, str]] = []
    for event in db.get_many(Event):
        if event.is_outcome:
            continue
        question = questions.get(event.extracted_for_question_id or "")
        for article_id in _article_ids(event):
            article = articles.get(article_id)
            record = quality.get(article_id)
            if article is None or record is None:
                continue
            verification = latest_verification.get((event.id, article.id))
            rows.append(
                {
                    "item_id": f"{event.id}::{article.id}",
                    "event_id": event.id,
                    "article_id": article.id,
                    "question_id": question.id if question else "",
                    "question_text": question.question_text if question else "",
                    "resolved_outcome": _ground_truth(question),
                    "event_title": event.title,
                    "event_description": event.description,
                    "claimed_date": _iso(event.occurred_date),
                    "domain": (
                        event.domain.value
                        if hasattr(event.domain, "value")
                        else str(event.domain)
                    ),
                    "article_title": article.title,
                    "article_source": article.source,
                    "article_published_date": _iso(article.published_date),
                    "article_url": article.url or "",
                    "automated_action": (
                        verification.action.value
                        if verification is not None
                        else "unvalidated"
                    ),
                    "clean_markdown": record.clean_markdown or "",
                    "normalized_content": record.normalized_content,
                }
            )
    return rows


def _stratified_sample(
    rows: List[Dict[str, str]],
    limit: int,
    seed: int,
) -> List[Dict[str, str]]:
    rng = random.Random(seed)
    groups: Dict[str, deque] = defaultdict(deque)
    for row in rows:
        stratum = f'{row["domain"]}::{row["automated_action"]}'
        groups[stratum].append(row)
    for domain, items in list(groups.items()):
        shuffled = list(items)
        rng.shuffle(shuffled)
        groups[domain] = deque(shuffled)

    selected: List[Dict[str, str]] = []
    domains = sorted(groups)
    while len(selected) < min(limit, len(rows)):
        added = False
        for domain in domains:
            if groups[domain] and len(selected) < limit:
                selected.append(groups[domain].popleft())
                added = True
        if not added:
            break
    rng.shuffle(selected)
    return selected


def _annotation_id(packet_id: str, item_id: str) -> str:
    value = f"event-source-annotation-v1|{packet_id}|{item_id}".encode("utf-8")
    return "ann_" + hashlib.sha256(value).hexdigest()[:20]


def _load_item_ids(path: Optional[Path]) -> List[str]:
    if path is None:
        return []
    item_ids = [
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if len(item_ids) != len(set(item_ids)):
        raise ValueError(f"Selection contains duplicate item IDs: {path}")
    return item_ids


def _select_candidates(
    rows: List[Dict[str, str]],
    limit: int,
    seed: int,
    selection_file: Optional[Path],
    exclude_selection_file: Optional[Path],
    unvalidated_only: bool,
) -> List[Dict[str, str]]:
    excluded = set(_load_item_ids(exclude_selection_file))
    eligible = [row for row in rows if row["item_id"] not in excluded]
    if unvalidated_only:
        eligible = [
            row for row in eligible if row["automated_action"] == "unvalidated"
        ]

    selected_ids = _load_item_ids(selection_file)
    if not selected_ids:
        return _stratified_sample(eligible, limit=limit, seed=seed)

    rows_by_id = {row["item_id"]: row for row in eligible}
    missing = [item_id for item_id in selected_ids if item_id not in rows_by_id]
    if missing:
        raise ValueError(
            "Selection contains unavailable event-source pairs: "
            + ", ".join(missing[:10])
        )
    if len(selected_ids) > limit:
        raise ValueError(
            f"Selection contains {len(selected_ids)} items but limit is {limit}"
        )
    return [rows_by_id[item_id] for item_id in selected_ids]


def build_packet(
    db_path: Path,
    dataset_version: str,
    output_dir: Path,
    packet_id: str,
    limit: int,
    seed: int,
    template_path: Path,
    selection_file: Optional[Path] = None,
    exclude_selection_file: Optional[Path] = None,
    unvalidated_only: bool = False,
    storage_namespace: Optional[str] = None,
) -> Path:
    """Build one blinded annotation packet and return its HTML path."""
    db = GenericDatabase(str(db_path))
    candidates = _candidate_rows(db, dataset_version)
    selected = _select_candidates(
        candidates,
        limit=limit,
        seed=seed,
        selection_file=selection_file,
        exclude_selection_file=exclude_selection_file,
        unvalidated_only=unvalidated_only,
    )
    if not selected:
        raise ValueError("No event-source pairs have completed cleaned evidence")

    output_dir.mkdir(parents=True, exist_ok=True)
    article_dir = output_dir / "articles"
    article_dir.mkdir(exist_ok=True)
    renderer = _renderer()
    public_rows: List[Dict[str, str]] = []
    written_articles = set()
    for row in selected:
        article_id = row["article_id"]
        if article_id not in written_articles:
            clean_name = f"{article_id}_cleaned.html"
            source_name = f"{article_id}_snapshot.html"
            (article_dir / clean_name).write_text(
                _render_document(row["clean_markdown"], renderer),
                encoding="utf-8",
            )
            (article_dir / source_name).write_text(
                _render_document(row["normalized_content"], renderer),
                encoding="utf-8",
            )
            written_articles.add(article_id)

        public = {
            key: value
            for key, value in row.items()
            if key
            not in {
                "clean_markdown",
                "normalized_content",
                "question_text",
                "resolved_outcome",
                "article_url",
                "automated_action",
            }
        }
        public["annotation_id"] = _annotation_id(packet_id, row["item_id"])
        public["review_mode"] = "annotation_study"
        public["packet_id"] = packet_id
        public["cleaned_path"] = f"articles/{article_id}_cleaned.html"
        public["snapshot_path"] = f"articles/{article_id}_snapshot.html"
        public_rows.append(public)

    queue_path = output_dir / "review_queue.csv"
    with queue_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(public_rows[0]))
        writer.writeheader()
        writer.writerows(public_rows)

    payload = json.dumps(public_rows, ensure_ascii=True).replace("</", "<\\/")
    template = template_path.read_text(encoding="utf-8")
    html_path = output_dir / "annotate.html"
    html_path.write_text(
        template.replace("__QUEUE_DATA__", payload)
        .replace(
            "__STORAGE_KEY__",
            "worldreasoner-event-annotation-"
            + (storage_namespace or packet_id),
        )
        .replace("__PACKET_ID__", packet_id),
        encoding="utf-8",
    )

    manifest = {
        "artifact": "event-source-annotation-packet",
        "review_mode": "annotation_study",
        "packet_id": packet_id,
        "dataset_version": dataset_version,
        "db_path": str(db_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "candidate_pairs": len(candidates),
        "selected_pairs": len(public_rows),
        "selection_file": str(selection_file) if selection_file else None,
        "exclude_selection_file": (
            str(exclude_selection_file) if exclude_selection_file else None
        ),
        "unvalidated_only": unvalidated_only,
        "storage_namespace": storage_namespace or packet_id,
        "domains": sorted({row["domain"] for row in public_rows}),
        "blinding": {
            "forecast_question_exposed": False,
            "resolved_outcome_exposed": False,
            "model_extractions_exposed": False,
            "model_verifications_exposed": False,
            "researcher_decisions_exposed": False,
            "quality_flags_exposed": False,
        },
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "index.md").write_text(
        "# Event-Source Annotation Packet\n\n"
        f"Packet: `{packet_id}`  \n"
        f"Items: {len(public_rows)}  \n"
        f"Dataset version: `{dataset_version}`\n\n"
        "Open [the annotation interface](annotate.html). Enter the assigned "
        "pseudonymous annotator ID, label every item independently, and export "
        "the completed CSV. Do not discuss labels with another annotator before "
        "submission.\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(public_rows)} blinded event-source pairs to {html_path}")
    return html_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/versions/v2_0/worldreasoner.db"),
    )
    parser.add_argument("--dataset-version", default="v2.0")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--packet-id", required=True)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20261003)
    parser.add_argument("--selection-file", type=Path)
    parser.add_argument("--exclude-selection-file", type=Path)
    parser.add_argument("--unvalidated-only", action="store_true")
    parser.add_argument("--storage-namespace")
    parser.add_argument(
        "--template",
        type=Path,
        default=Path("scripts/analysis/templates/event_annotation.template"),
    )
    args = parser.parse_args()
    build_packet(
        db_path=args.db,
        dataset_version=args.dataset_version,
        output_dir=args.output,
        packet_id=args.packet_id,
        limit=args.limit,
        seed=args.seed,
        template_path=args.template,
        selection_file=args.selection_file,
        exclude_selection_file=args.exclude_selection_file,
        unvalidated_only=args.unvalidated_only,
        storage_namespace=args.storage_namespace,
    )


if __name__ == "__main__":
    main()
