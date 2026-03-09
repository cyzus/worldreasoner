"""Question management with cascade support.

Extracted from db_manager.py for use by the unified CLI.
CLI wrapper that delegates domain logic to QuestionService.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from src.core.database import GenericDatabase
from src.domain.models import Article, Event, Question, CausalHypothesis
from src.services.question_service import QuestionService
from src.services.question_filters import (
    filter_resolved_questions,
    filter_by_quality_score,
)


@dataclass
class QuestionFilter:
    """Filter criteria for question selection."""

    source: Optional[str] = None
    domain: Optional[str] = None
    resolved_only: bool = False
    has_evidence: Optional[bool] = None
    min_quality_score: Optional[float] = None


class QuestionManager:
    """Manages questions and their related entities with cascade support.

    CLI wrapper that delegates domain logic to QuestionService.
    """

    def __init__(self, db: GenericDatabase):
        """Initialize with a database instance.

        Args:
            db: GenericDatabase instance to use
        """
        self.db = db
        self.service = QuestionService(db)

    def has_evidence(self, question_id: str) -> bool:
        """Check if question has evidence (causal hypotheses)."""
        return self.service.has_evidence(question_id)

    def get_evidence_status(self, questions: List[Question]) -> Dict[str, bool]:
        """Bulk check if questions have evidence."""
        return self.service.get_evidence_status(questions)

    def query_questions(
        self, filter_obj: QuestionFilter, limit: int = 50
    ) -> List[Question]:
        """Query questions with advanced filtering."""
        filters = {}
        if filter_obj.source:
            filters["source"] = filter_obj.source
        if filter_obj.domain:
            filters["domain"] = filter_obj.domain

        # Reuse database layer for efficient querying
        questions = self.db.get_many(Question, filters=filters)

        # Apply additional filters
        filtered_questions = questions

        # Filter by resolution status
        if filter_obj.resolved_only:
            filtered_questions = filter_resolved_questions(
                filtered_questions, resolved_only=True
            )

        # Filter by quality score
        if filter_obj.min_quality_score is not None:
            filtered_questions = filter_by_quality_score(
                filtered_questions, filter_obj.min_quality_score
            )

        # Filter by evidence status (requires iteration for has_evidence check)
        if filter_obj.has_evidence is not None:
            filtered_questions = [
                q
                for q in filtered_questions
                if (filter_obj.has_evidence and self.has_evidence(q.id))
                or (not filter_obj.has_evidence and not self.has_evidence(q.id))
            ]

        # Sort by quality score descending, then by resolution date
        filtered_questions.sort(
            key=lambda q: (
                -(q.quality_score or 0.0),
                q.resolution_date or datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        )

        return filtered_questions[:limit]

    def get_stats(self) -> Dict[str, int]:
        """Get counts for all tables."""
        return {
            "questions": self.db.count(Question),
            "events": self.db.count(Event),
            "articles": self.db.count(Article),
            "causal_hypotheses": self.db.count(CausalHypothesis),
        }

    def list_questions(
        self, domain: Optional[str] = None, limit: int = 50, show_related: bool = False
    ) -> List[Dict]:
        """List questions with optional filtering."""
        filters = {"domain": domain} if domain else {}
        questions = self.db.get_many(Question, filters=filters)[:limit]

        results = []
        for q in questions:
            item = {
                "id": q.id,
                "question_text": q.question_text[:80] + "..."
                if len(q.question_text) > 80
                else q.question_text,
                "domain": q.domain.value if hasattr(q.domain, "value") else q.domain,
                "type": q.question_type.value
                if hasattr(q.question_type, "value")
                else q.question_type,
                "quality_score": q.quality_score,
                "resolution_date": q.resolution_date.isoformat()
                if q.resolution_date
                else None,
            }
            if show_related:
                from src.analysis.graph_analysis import resolve_target_event_id

                item["target_event_id"] = resolve_target_event_id(q, self.db)
                item["related_event_count"] = len(q.related_event_ids)
            results.append(item)

        return results

    def show_question(self, question_id: str) -> Optional[Dict]:
        """Show detailed question info with all related entities."""
        question = self.db.get(Question, question_id)
        if not question:
            return None

        # Get related events
        event_ids = []
        if question.outcome_event_ids:
            event_ids.extend(question.outcome_event_ids)
        if question.target_event_id:  # Legacy fallback
            event_ids.append(question.target_event_id)
        event_ids.extend(question.related_event_ids)

        events = []
        article_ids = set()
        for eid in event_ids:
            event = self.db.get(Event, eid)
            if event:
                events.append(
                    {
                        "id": event.id,
                        "title": event.title,
                        "status": event.status.value
                        if hasattr(event.status, "value")
                        else event.status,
                        "article_count": len(event.article_ids),
                    }
                )
                article_ids.update(event.article_ids)

        # Get causal hypotheses referencing this question
        all_hypotheses = self.db.get_many(CausalHypothesis)
        related_hypotheses = [
            h for h in all_hypotheses if question_id in h.discovered_by_question_ids
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
                    "relation_type": h.relation_type.value
                    if hasattr(h.relation_type, "value")
                    else h.relation_type,
                    "confidence": h.confidence,
                }
                for h in related_hypotheses
            ],
        }

    def analyze_cascade(self, question_id: str) -> Dict:
        """Analyze what would be deleted if this question is removed."""
        return self.service.analyze_cascade(question_id)

    def delete_question(
        self, question_id: str, cascade: bool = True, dry_run: bool = False
    ) -> Dict:
        """Delete a question and optionally cascade to related entities."""
        return self.service.delete_question(question_id, cascade, dry_run)

    def delete_event(
        self, event_id: str, cascade: bool = True, dry_run: bool = False
    ) -> Dict:
        """Delete an event and cascade to related hypotheses/articles."""
        return self.service.delete_event(event_id, cascade, dry_run)

    def clear_evidence(
        self, question_id: str, cascade: bool = True, dry_run: bool = False
    ) -> Dict:
        """Remove all evidence pipeline data for a question WITHOUT deleting the question.

        For CLI use with detailed output. Pipeline code should use clear_evidence_simple().
        """
        if dry_run:
            # Need full analysis for dry run
            analysis = self.service.analyze_cascade(question_id)
            if "error" in analysis:
                return analysis

            return {
                "dry_run": True,
                "question_id": question_id,
                "would_delete": {
                    "articles": analysis["orphaned"]["articles"],
                    "events": analysis["orphaned"]["events"],
                    "causal_hypotheses": analysis["orphaned"][
                        "causal_hypotheses_delete"
                    ],
                },
                "would_update": {
                    "causal_hypotheses": analysis["shared"]["causal_hypotheses_update"],
                },
                "provenance_stats": analysis["provenance_stats"],
                "summary": {
                    "articles": len(analysis["orphaned"]["articles"]),
                    "events": len(analysis["orphaned"]["events"]),
                    "hypotheses_delete": len(
                        analysis["orphaned"]["causal_hypotheses_delete"]
                    ),
                    "hypotheses_update": len(
                        analysis["shared"]["causal_hypotheses_update"]
                    ),
                },
            }

        # Delegate to service and wrap result
        counts = self.service.clear_evidence(question_id, cascade)
        return {
            "success": True,
            "question_id": question_id,
            "deleted": {
                "articles": [],  # Service doesn't track IDs, just counts
                "events": [],
                "causal_hypotheses": [],
                "hypotheses_updated": [],
            },
            "summary": counts,
        }

    def clear_evidence_simple(
        self, question_id: str, cascade: bool = True
    ) -> Dict[str, int]:
        """Simplified evidence clearing for pipeline use (no dry-run, returns counts)."""
        return self.service.clear_evidence(question_id, cascade)

    def update_question(self, question_id: str, updates: Dict) -> Dict:
        """Update specific fields on a question."""
        return self.service.update_question(question_id, updates)
