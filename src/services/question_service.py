"""Question domain service.

Contains pure domain logic without CLI dependencies.
Used by both CLI and pipelines to break circular dependency.
"""

from typing import Dict, List
from datetime import datetime, timezone

from src.core.database import GenericDatabase
from src.domain.models import Question, Article, Event, CausalHypothesis
from src.domain.models.event_outcome_impact import EventOutcomeImpact
from src.utils.logging import logger


class QuestionService:
    """Domain service for question operations.

    Contains pure domain logic extracted from QuestionManager.
    No CLI dependencies - can be used by pipelines directly.
    """

    def __init__(self, db: GenericDatabase):
        self.db = db

    def has_evidence(self, question_id: str) -> bool:
        """Check if question has completed evidence (articles + causal_explanation)."""
        from src.services.question_monitor_service import QuestionMonitorService

        return QuestionMonitorService(self.db).check_satisfaction(question_id).is_satisfied

    def get_evidence_status(self, questions: List[Question]) -> Dict[str, bool]:
        """Bulk check if questions have completed evidence."""
        from src.services.question_monitor_service import QuestionMonitorService

        processed = QuestionMonitorService(self.db).get_processed_question_ids(questions)
        return {q.id: (q.id in processed) for q in questions}

    def analyze_cascade(self, question_id: str) -> Dict:
        """Analyze what would be deleted if this question is removed.

        Uses explicit provenance fields (collected_for_question_id, extracted_for_question_id)
        with fallback to metadata for backward compatibility.

        Returns:
            Dict with 'orphaned' (will delete) and 'shared' (will keep) items
        """
        question = self.db.get(Question, question_id)
        if not question:
            return {"error": f"Question {question_id} not found"}

        # === ARTICLES: Find articles collected for this question ===
        all_articles = self.db.get_many(Article)

        # Articles with explicit provenance field
        articles_by_provenance = [
            a.id for a in all_articles if a.collected_for_question_id == question_id
        ]

        # Fallback: articles with metadata (for pre-migration data)
        articles_by_metadata = [
            a.id
            for a in all_articles
            if a.collected_for_question_id is None  # Not already counted
            and a.metadata.get("related_question_ids")
            and question_id in a.metadata["related_question_ids"]
        ]

        orphaned_article_ids = set(articles_by_provenance + articles_by_metadata)

        # === EVENTS: Find events extracted for this question ===
        all_events = self.db.get_many(Event)

        # Events with explicit provenance field
        events_by_provenance = [
            e.id for e in all_events if e.extracted_for_question_id == question_id
        ]

        # Fallback: events with metadata (for pre-migration data)
        events_by_metadata = [
            e.id
            for e in all_events
            if e.extracted_for_question_id is None  # Not already counted
            and e.metadata.get("related_question_ids")
            and question_id in e.metadata["related_question_ids"]
        ]

        orphaned_event_ids = set(events_by_provenance + events_by_metadata)

        # === Also include events referenced in question but NOT pre-existing ===
        # Pre-existing events (target_event_id, related_event_ids) should be kept
        pre_existing_event_ids = set()
        if question.outcome_event_ids:
            pre_existing_event_ids.update(question.outcome_event_ids)
        if question.target_event_id:  # Legacy fallback
            pre_existing_event_ids.add(question.target_event_id)
        pre_existing_event_ids.update(question.related_event_ids)

        # Don't delete pre-existing events (they weren't created by evidence pipeline)
        orphaned_event_ids -= pre_existing_event_ids

        # === CAUSAL HYPOTHESES ===
        all_hypotheses = self.db.get_many(CausalHypothesis)

        hypotheses_to_delete = []  # Source or target event will be deleted
        hypotheses_to_update = []  # Question ID in discovered_by list (but hypothesis kept)

        for h in all_hypotheses:
            # Delete if either endpoint is an orphaned event
            if (
                h.source_event_id in orphaned_event_ids
                or h.target_event_id in orphaned_event_ids
            ):
                hypotheses_to_delete.append(h.id)
            # Update if this question discovered it (and hypothesis won't be deleted)
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
                "pre_existing_events": list(pre_existing_event_ids),
                "causal_hypotheses_update": hypotheses_to_update,
            },
            "provenance_stats": {
                "articles_by_field": len(articles_by_provenance),
                "articles_by_metadata": len(articles_by_metadata),
                "events_by_field": len(events_by_provenance),
                "events_by_metadata": len(events_by_metadata),
            },
            "summary": {
                "will_delete_events": len(orphaned_event_ids),
                "will_delete_articles": len(orphaned_article_ids),
                "will_delete_hypotheses": len(hypotheses_to_delete),
                "will_update_hypotheses": len(hypotheses_to_update),
                "will_keep_pre_existing_events": len(pre_existing_event_ids),
            },
        }

    def clear_evidence(self, question_id: str, cascade: bool = True) -> Dict[str, int]:
        """Clear evidence data for a question.

        This is the core clearing logic used by both CLI and pipelines.
        Returns simple counts for easy consumption.

        Returns: {"articles": int, "events": int, "hypotheses": int}
        """
        question = self.db.get(Question, question_id)
        if not question:
            logger.warning(f"Question {question_id} not found, cannot clear evidence")
            return {"articles": 0, "events": 0, "hypotheses": 0}

        analysis = self.analyze_cascade(question_id)
        if "error" in analysis:
            return {"articles": 0, "events": 0, "hypotheses": 0}

        deleted = {
            "articles": [],
            "events": [],
            "causal_hypotheses": [],
            "hypotheses_updated": [],
        }

        # Delete causal hypotheses where source/target event will be deleted
        for hid in analysis["orphaned"]["causal_hypotheses_delete"]:
            if self.db.delete(CausalHypothesis, hid):
                deleted["causal_hypotheses"].append(hid)

        # Update hypotheses that referenced this question (remove from discovered_by)
        for hid in analysis["shared"]["causal_hypotheses_update"]:
            h = self.db.get(CausalHypothesis, hid)
            if h and question_id in h.discovered_by_question_ids:
                h.discovered_by_question_ids.remove(question_id)
                self.db.save(CausalHypothesis, h)
                deleted["hypotheses_updated"].append(hid)

        # Delete events extracted for this question
        for eid in analysis["orphaned"]["events"]:
            if self.db.delete(Event, eid):
                deleted["events"].append(eid)

        # Delete articles collected for this question
        for aid in analysis["orphaned"]["articles"]:
            if self.db.delete(Article, aid):
                deleted["articles"].append(aid)

        # Delete event outcome impacts for this question
        impacts = self.db.get_many(
            EventOutcomeImpact, filters={"question_id": question_id}
        )
        deleted["impacts"] = []
        for impact in impacts:
            if self.db.delete(EventOutcomeImpact, impact.id):
                deleted["impacts"].append(impact.id)

        # Reset graph fields so question can be reprocessed
        question.causal_explanation = None
        question.graph_built = False
        question.graph_build_error = None
        self.db.save(Question, question)

        logger.debug(
            f"Cleared evidence for {question_id}: "
            f"{len(deleted['articles'])} articles, {len(deleted['events'])} events, "
            f"{len(deleted['causal_hypotheses'])} hypotheses, {len(deleted['impacts'])} impacts"
        )

        # Return simple count dict
        return {
            "articles": len(deleted["articles"]),
            "events": len(deleted["events"]),
            "hypotheses": len(deleted["causal_hypotheses"]),
            "impacts": len(deleted["impacts"]),
        }

    def clear_graph(self, question_id: str) -> Dict[str, int]:
        """Clear only graph data for a question (events, hypotheses, graph flags).

        Keeps articles and causal_explanation intact so the graph can be rebuilt
        without re-running the evidence pipeline.
        """
        question = self.db.get(Question, question_id)
        if not question:
            return {"events": 0, "hypotheses": 0, "impacts": 0}

        analysis = self.analyze_cascade(question_id)
        deleted = {"events": [], "hypotheses": [], "impacts": []}

        for hid in analysis.get("orphaned", {}).get("causal_hypotheses_delete", []):
            if self.db.delete(CausalHypothesis, hid):
                deleted["hypotheses"].append(hid)

        for hid in analysis.get("shared", {}).get("causal_hypotheses_update", []):
            h = self.db.get(CausalHypothesis, hid)
            if h and question_id in h.discovered_by_question_ids:
                h.discovered_by_question_ids.remove(question_id)
                self.db.save(CausalHypothesis, h)

        for eid in analysis.get("orphaned", {}).get("events", []):
            if self.db.delete(Event, eid):
                deleted["events"].append(eid)

        impacts = self.db.get_many(EventOutcomeImpact, filters={"question_id": question_id})
        for impact in impacts:
            if self.db.delete(EventOutcomeImpact, impact.id):
                deleted["impacts"].append(impact.id)

        question.graph_built = False
        question.graph_build_error = None
        self.db.save(Question, question)

        return {
            "events": len(deleted["events"]),
            "hypotheses": len(deleted["hypotheses"]),
            "impacts": len(deleted["impacts"]),
        }

    def delete_question(
        self, question_id: str, cascade: bool = True, dry_run: bool = False
    ) -> Dict:
        """Delete a question and optionally cascade to related entities."""
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
                "would_update": analysis["shared"]["causal_hypotheses_update"]
                if cascade
                else [],
                "summary": analysis["summary"],
            }

        deleted = {
            "question": question_id,
            "events": [],
            "articles": [],
            "causal_hypotheses": [],
            "hypotheses_updated": [],
        }

        # Delete question first
        self.db.delete(Question, question_id)

        if cascade:
            # Delete orphaned causal hypotheses
            for hid in analysis["orphaned"]["causal_hypotheses_delete"]:
                if self.db.delete(CausalHypothesis, hid):
                    deleted["causal_hypotheses"].append(hid)

            # Update hypotheses that referenced this question
            for hid in analysis["shared"]["causal_hypotheses_update"]:
                h = self.db.get(CausalHypothesis, hid)
                if h and question_id in h.discovered_by_question_ids:
                    h.discovered_by_question_ids.remove(question_id)
                    self.db.save(CausalHypothesis, h)
                    deleted["hypotheses_updated"].append(hid)

            # Delete orphaned events
            for eid in analysis["orphaned"]["events"]:
                if self.db.delete(Event, eid):
                    deleted["events"].append(eid)

            # Delete orphaned articles
            for aid in analysis["orphaned"]["articles"]:
                if self.db.delete(Article, aid):
                    deleted["articles"].append(aid)

        return {
            "success": True,
            "deleted": deleted,
            "summary": {
                "questions": 1,
                "events": len(deleted["events"]),
                "articles": len(deleted["articles"]),
                "causal_hypotheses": len(deleted["causal_hypotheses"]),
                "hypotheses_updated": len(deleted["hypotheses_updated"]),
            },
        }

    def delete_event(
        self, event_id: str, cascade: bool = True, dry_run: bool = False
    ) -> Dict:
        """Delete an event and cascade to related hypotheses/articles."""
        event = self.db.get(Event, event_id)
        if not event:
            return {"error": f"Event {event_id} not found"}

        # Find hypotheses that reference this event
        all_hypotheses = self.db.get_many(CausalHypothesis)
        hypotheses_to_delete = [
            h.id
            for h in all_hypotheses
            if h.source_event_id == event_id or h.target_event_id == event_id
        ]

        # Find questions that reference this event
        all_questions = self.db.get_many(Question)
        referencing_questions = [
            q.id
            for q in all_questions
            if event_id in (q.outcome_event_ids or [])
            or q.target_event_id == event_id
            or event_id in (q.related_event_ids or [])
        ]

        if referencing_questions:
            return {
                "error": f"Event is referenced by questions: {referencing_questions}",
                "hint": "Delete or update these questions first, or use delete_question with cascade",
            }

        if dry_run:
            return {
                "dry_run": True,
                "would_delete": {
                    "event": event_id,
                    "causal_hypotheses": hypotheses_to_delete if cascade else [],
                    "articles": event.article_ids if cascade else [],
                },
            }

        deleted = {"event": event_id, "causal_hypotheses": [], "articles": []}

        if cascade:
            for hid in hypotheses_to_delete:
                if self.db.delete(CausalHypothesis, hid):
                    deleted["causal_hypotheses"].append(hid)

            # Only delete articles not referenced by other events
            all_events = self.db.get_many(Event)
            other_article_ids = set()
            for e in all_events:
                if e.id != event_id:
                    other_article_ids.update(e.article_ids)

            for aid in event.article_ids:
                if aid not in other_article_ids:
                    if self.db.delete(Article, aid):
                        deleted["articles"].append(aid)

        self.db.delete(Event, event_id)
        return {"success": True, "deleted": deleted}

    def update_question(self, question_id: str, updates: Dict) -> Dict:
        """Update specific fields on a question."""
        question = self.db.get(Question, question_id)
        if not question:
            return {"error": f"Question {question_id} not found"}

        # Apply updates (protect immutable fields)
        immutable_fields = {"id", "created_at"}
        data = question.model_dump()
        for key, value in updates.items():
            if key in immutable_fields:
                logger.warning(f"Skipping immutable field '{key}' in update_question")
                continue
            if key in data:
                data[key] = value

        # Rebuild and save
        updated_question = Question(**data)
        updated_question.updated_at = datetime.now(timezone.utc)
        self.db.save(Question, updated_question)

        return {"success": True, "updated": list(updates.keys())}
