"""Database management CLI for WorldReasoner.

Provides question-centric CRUD operations with cascading deletes.

Usage:
    python -m src.cli.db_manager list questions
    python -m src.cli.db_manager show question <id>
    python -m src.cli.db_manager delete question <id> [--dry-run] [--cascade]
    python -m src.cli.db_manager stats
"""

import argparse
import json
import sys
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from ..core.database import Database, GenericDatabase
from ..domain.models import Article, Event, Question, CausalHypothesis


class QuestionManager:
    """Manages questions and their related entities with cascade support."""

    def __init__(self, db_path: str = "worldreasoner.db"):
        self.db = Database(db_path)
        self.generic_db = GenericDatabase(db_path)

    def get_stats(self) -> Dict[str, int]:
        """Get counts for all tables."""
        return {
            "questions": self.generic_db.count(Question),
            "events": self.generic_db.count(Event),
            "articles": self.generic_db.count(Article),
            "causal_hypotheses": self.generic_db.count(CausalHypothesis),
        }

    def list_questions(
        self,
        domain: Optional[str] = None,
        limit: int = 50,
        show_related: bool = False
    ) -> List[Dict]:
        """List questions with optional filtering."""
        questions = self.db.get_questions(domain=domain)[:limit]

        results = []
        for q in questions:
            item = {
                "id": q.id,
                "question_text": q.question_text[:80] + "..." if len(q.question_text) > 80 else q.question_text,
                "domain": q.domain.value if hasattr(q.domain, 'value') else q.domain,
                "type": q.question_type.value if hasattr(q.question_type, 'value') else q.question_type,
                "quality_score": q.quality_score,
                "resolution_date": q.resolution_date.isoformat() if q.resolution_date else None,
            }
            if show_related:
                item["target_event_id"] = q.target_event_id
                item["related_event_count"] = len(q.related_event_ids)
            results.append(item)

        return results

    def show_question(self, question_id: str) -> Optional[Dict]:
        """Show detailed question info with all related entities."""
        question = self.db.get_question(question_id)
        if not question:
            return None

        # Get related events
        event_ids = []
        if question.target_event_id:
            event_ids.append(question.target_event_id)
        event_ids.extend(question.related_event_ids)

        events = []
        article_ids = set()
        for eid in event_ids:
            event = self.db.get_event(eid)
            if event:
                events.append({
                    "id": event.id,
                    "title": event.title,
                    "status": event.status.value if hasattr(event.status, 'value') else event.status,
                    "article_count": len(event.article_ids)
                })
                article_ids.update(event.article_ids)

        # Get causal hypotheses referencing this question
        all_hypotheses = self.generic_db.get_many(CausalHypothesis)
        related_hypotheses = [
            h for h in all_hypotheses
            if question_id in h.discovered_by_question_ids
        ]

        return {
            "question": question.model_dump(),
            "events": events,
            "article_count": len(article_ids),
            "causal_hypotheses": [
                {
                    "id": h.id,
                    "source_event_id": h.source_event_id,
                    "target_event_id": h.target_event_id,
                    "relation_type": h.relation_type.value if hasattr(h.relation_type, 'value') else h.relation_type,
                    "confidence": h.confidence
                }
                for h in related_hypotheses
            ]
        }

    def analyze_cascade(self, question_id: str) -> Dict:
        """Analyze what would be deleted if this question is removed.

        Returns:
            Dict with 'orphaned' (will delete) and 'shared' (will keep) items
        """
        question = self.db.get_question(question_id)
        if not question:
            return {"error": f"Question {question_id} not found"}

        # Collect all event IDs referenced by this question
        question_event_ids = set()
        if question.target_event_id:
            question_event_ids.add(question.target_event_id)
        question_event_ids.update(question.related_event_ids)

        # Find which events are referenced by OTHER questions
        all_questions = self.generic_db.get_many(Question)
        shared_event_ids = set()
        for q in all_questions:
            if q.id == question_id:
                continue
            if q.target_event_id and q.target_event_id in question_event_ids:
                shared_event_ids.add(q.target_event_id)
            for eid in q.related_event_ids:
                if eid in question_event_ids:
                    shared_event_ids.add(eid)

        orphaned_event_ids = question_event_ids - shared_event_ids

        # Collect article IDs from orphaned events
        orphaned_article_ids = set()
        shared_article_ids = set()

        for eid in orphaned_event_ids:
            event = self.db.get_event(eid)
            if event:
                orphaned_article_ids.update(event.article_ids)

        # Check if articles are referenced by non-orphaned events
        all_events = self.generic_db.get_many(Event)
        for event in all_events:
            if event.id not in orphaned_event_ids:
                for aid in event.article_ids:
                    if aid in orphaned_article_ids:
                        shared_article_ids.add(aid)

        orphaned_article_ids -= shared_article_ids

        # Find causal hypotheses to update or delete
        all_hypotheses = self.generic_db.get_many(CausalHypothesis)

        hypotheses_to_delete = []  # Source or target event is orphaned
        hypotheses_to_update = []  # Question ID in discovered_by list

        for h in all_hypotheses:
            # Delete if either endpoint is an orphaned event
            if h.source_event_id in orphaned_event_ids or h.target_event_id in orphaned_event_ids:
                hypotheses_to_delete.append(h.id)
            # Update if this question discovered it (and won't be deleted)
            elif question_id in h.discovered_by_question_ids:
                hypotheses_to_update.append(h.id)

        return {
            "question_id": question_id,
            "orphaned": {
                "events": list(orphaned_event_ids),
                "articles": list(orphaned_article_ids),
                "causal_hypotheses_delete": hypotheses_to_delete,
            },
            "shared": {
                "events": list(shared_event_ids),
                "articles": list(shared_article_ids),
                "causal_hypotheses_update": hypotheses_to_update,
            },
            "summary": {
                "will_delete_events": len(orphaned_event_ids),
                "will_delete_articles": len(orphaned_article_ids),
                "will_delete_hypotheses": len(hypotheses_to_delete),
                "will_update_hypotheses": len(hypotheses_to_update),
                "will_keep_shared_events": len(shared_event_ids),
            }
        }

    def delete_question(
        self,
        question_id: str,
        cascade: bool = True,
        dry_run: bool = False
    ) -> Dict:
        """Delete a question and optionally cascade to related entities.

        Args:
            question_id: Question to delete
            cascade: If True, delete orphaned events/articles/hypotheses
            dry_run: If True, only report what would be deleted

        Returns:
            Summary of deletions performed
        """
        analysis = self.analyze_cascade(question_id)
        if "error" in analysis:
            return analysis

        if dry_run:
            would_delete = {"question": question_id}
            if cascade:
                would_delete.update(analysis["orphaned"])
            return {
                "dry_run": True,
                "would_delete": would_delete,
                "would_update": analysis["shared"]["causal_hypotheses_update"] if cascade else [],
                "summary": analysis["summary"]
            }

        deleted = {
            "question": question_id,
            "events": [],
            "articles": [],
            "causal_hypotheses": [],
            "hypotheses_updated": []
        }

        # Delete question first
        self.generic_db.delete(Question, question_id)

        if cascade:
            # Delete orphaned causal hypotheses
            for hid in analysis["orphaned"]["causal_hypotheses_delete"]:
                if self.generic_db.delete(CausalHypothesis, hid):
                    deleted["causal_hypotheses"].append(hid)

            # Update hypotheses that referenced this question
            for hid in analysis["shared"]["causal_hypotheses_update"]:
                h = self.generic_db.get(CausalHypothesis, hid)
                if h and question_id in h.discovered_by_question_ids:
                    h.discovered_by_question_ids.remove(question_id)
                    self.generic_db.save(CausalHypothesis, h)
                    deleted["hypotheses_updated"].append(hid)

            # Delete orphaned events
            for eid in analysis["orphaned"]["events"]:
                if self.generic_db.delete(Event, eid):
                    deleted["events"].append(eid)

            # Delete orphaned articles
            for aid in analysis["orphaned"]["articles"]:
                if self.generic_db.delete(Article, aid):
                    deleted["articles"].append(aid)

        return {
            "success": True,
            "deleted": deleted,
            "summary": {
                "questions": 1,
                "events": len(deleted["events"]),
                "articles": len(deleted["articles"]),
                "causal_hypotheses": len(deleted["causal_hypotheses"]),
                "hypotheses_updated": len(deleted["hypotheses_updated"])
            }
        }

    def delete_event(self, event_id: str, cascade: bool = True, dry_run: bool = False) -> Dict:
        """Delete an event and cascade to related hypotheses/articles."""
        event = self.db.get_event(event_id)
        if not event:
            return {"error": f"Event {event_id} not found"}

        # Find hypotheses that reference this event
        all_hypotheses = self.generic_db.get_many(CausalHypothesis)
        hypotheses_to_delete = [
            h.id for h in all_hypotheses
            if h.source_event_id == event_id or h.target_event_id == event_id
        ]

        # Find questions that reference this event
        all_questions = self.generic_db.get_many(Question)
        referencing_questions = [
            q.id for q in all_questions
            if q.target_event_id == event_id or event_id in q.related_event_ids
        ]

        if referencing_questions:
            return {
                "error": f"Event is referenced by questions: {referencing_questions}",
                "hint": "Delete or update these questions first, or use delete_question with cascade"
            }

        if dry_run:
            return {
                "dry_run": True,
                "would_delete": {
                    "event": event_id,
                    "causal_hypotheses": hypotheses_to_delete if cascade else [],
                    "articles": event.article_ids if cascade else []
                }
            }

        deleted = {"event": event_id, "causal_hypotheses": [], "articles": []}

        if cascade:
            for hid in hypotheses_to_delete:
                if self.generic_db.delete(CausalHypothesis, hid):
                    deleted["causal_hypotheses"].append(hid)

            # Only delete articles not referenced by other events
            all_events = self.generic_db.get_many(Event)
            other_article_ids = set()
            for e in all_events:
                if e.id != event_id:
                    other_article_ids.update(e.article_ids)

            for aid in event.article_ids:
                if aid not in other_article_ids:
                    if self.generic_db.delete(Article, aid):
                        deleted["articles"].append(aid)

        self.generic_db.delete(Event, event_id)
        return {"success": True, "deleted": deleted}

    def update_question(self, question_id: str, updates: Dict) -> Dict:
        """Update specific fields on a question."""
        question = self.db.get_question(question_id)
        if not question:
            return {"error": f"Question {question_id} not found"}

        # Apply updates
        data = question.model_dump()
        for key, value in updates.items():
            if key in data:
                data[key] = value

        # Rebuild and save
        updated_question = Question(**data)
        updated_question.updated_at = datetime.now()
        self.db.save_question(updated_question)

        return {"success": True, "updated": list(updates.keys())}


def print_json(data, indent=2):
    """Pretty print JSON data."""
    print(json.dumps(data, indent=indent, default=str))


def main():
    parser = argparse.ArgumentParser(
        description="WorldReasoner Database Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s stats
  %(prog)s list questions --domain finance --limit 10
  %(prog)s show question q_123
  %(prog)s delete question q_123 --dry-run
  %(prog)s delete question q_123 --cascade
        """
    )
    parser.add_argument("--db", default="worldreasoner.db", help="Database path")

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # Stats command
    subparsers.add_parser("stats", help="Show database statistics")

    # List command
    list_parser = subparsers.add_parser("list", help="List entities")
    list_parser.add_argument("entity", choices=["questions", "events", "articles"])
    list_parser.add_argument("--domain", help="Filter by domain")
    list_parser.add_argument("--limit", type=int, default=50, help="Max results")
    list_parser.add_argument("--related", action="store_true", help="Show related entity counts")

    # Show command
    show_parser = subparsers.add_parser("show", help="Show entity details")
    show_parser.add_argument("entity", choices=["question", "event"])
    show_parser.add_argument("id", help="Entity ID")

    # Delete command
    delete_parser = subparsers.add_parser("delete", help="Delete entity")
    delete_parser.add_argument("entity", choices=["question", "event"])
    delete_parser.add_argument("id", help="Entity ID")
    delete_parser.add_argument("--dry-run", action="store_true", help="Preview without deleting")
    delete_parser.add_argument("--no-cascade", action="store_true", help="Don't delete related entities")

    # Analyze command
    analyze_parser = subparsers.add_parser("analyze", help="Analyze cascade impact")
    analyze_parser.add_argument("entity", choices=["question"])
    analyze_parser.add_argument("id", help="Entity ID")

    # Update command
    update_parser = subparsers.add_parser("update", help="Update entity fields")
    update_parser.add_argument("entity", choices=["question"])
    update_parser.add_argument("id", help="Entity ID")
    update_parser.add_argument("--set", nargs=2, action="append", metavar=("FIELD", "VALUE"),
                               help="Field and value to update (can repeat)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    manager = QuestionManager(args.db)

    if args.command == "stats":
        print_json(manager.get_stats())

    elif args.command == "list":
        if args.entity == "questions":
            result = manager.list_questions(
                domain=args.domain,
                limit=args.limit,
                show_related=args.related
            )
            print_json(result)
        elif args.entity == "events":
            events = manager.generic_db.get_many(Event)[:args.limit]
            print_json([{"id": e.id, "title": e.title, "domain": e.domain.value} for e in events])
        elif args.entity == "articles":
            articles = manager.generic_db.get_many(Article)[:args.limit]
            print_json([{"id": a.id, "title": a.title[:60], "source": a.source} for a in articles])

    elif args.command == "show":
        if args.entity == "question":
            result = manager.show_question(args.id)
            if result:
                print_json(result)
            else:
                print(f"Question {args.id} not found", file=sys.stderr)
                sys.exit(1)
        elif args.entity == "event":
            event = manager.db.get_event(args.id)
            if event:
                print_json(event.model_dump())
            else:
                print(f"Event {args.id} not found", file=sys.stderr)
                sys.exit(1)

    elif args.command == "analyze":
        if args.entity == "question":
            result = manager.analyze_cascade(args.id)
            print_json(result)

    elif args.command == "delete":
        cascade = not args.no_cascade
        if args.entity == "question":
            result = manager.delete_question(args.id, cascade=cascade, dry_run=args.dry_run)
        elif args.entity == "event":
            result = manager.delete_event(args.id, cascade=cascade, dry_run=args.dry_run)
        print_json(result)

    elif args.command == "update":
        if not args.set:
            print("No updates specified. Use --set FIELD VALUE", file=sys.stderr)
            sys.exit(1)
        updates = {field: value for field, value in args.set}
        result = manager.update_question(args.id, updates)
        print_json(result)


if __name__ == "__main__":
    main()
