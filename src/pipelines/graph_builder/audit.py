"""Audit pipeline for graph building."""

from typing import Dict, Any

from src.core.database import GenericDatabase
from src.domain.models import Event, CausalHypothesis, Question


class GraphAuditPipeline:
    """Validates staged graph data before committing.

    (Note: Full staging tables not yet implemented in DB model, so this
     currently runs validation on the actual tables and flags issues.)
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.db = GenericDatabase(db_path)

    def audit_question(self, question_id: str) -> Dict[str, Any]:
        """Audit the graph for a specific question."""
        q = self.db.get(Question, question_id)
        if not q:
            return {"status": "error", "message": f"Question {question_id} not found."}

        # Find events
        events = self.db.get_many(Event)
        q_events = [
            e
            for e in events
            if getattr(e, "extracted_for_question_id", None) == question_id
        ]

        # Find hypotheses
        hyps = self.db.get_many(CausalHypothesis)
        q_hyps = [h for h in hyps if question_id in h.discovered_by_question_ids]

        issues = []

        # 1. Check chronologies
        for h in q_hyps:
            source = next((e for e in events if e.id == h.source_event_id), None)
            target = next((e for e in events if e.id == h.target_event_id), None)

            if not source or not target:
                issues.append(f"Hypothesis {h.id} references missing events.")
                continue

            sd = source.occurred_date or source.predicted_date
            td = target.occurred_date or target.predicted_date

            if sd and td and sd > td:
                issues.append(
                    f"Chronology violation: {source.title} ({sd}) > {target.title} ({td})"
                )

        # 2. Check orphan actual outcome
        actual_outcome_id = None
        if q.outcome_event_ids:
            for oid in q.outcome_event_ids:
                e = next((ev for ev in events if ev.id == oid), None)
                if e and getattr(e, "is_actual_outcome", False):
                    actual_outcome_id = oid
                    break

        if actual_outcome_id:
            has_incoming = any(h.target_event_id == actual_outcome_id for h in q_hyps)
            if not has_incoming:
                issues.append(
                    f"Actual outcome event {actual_outcome_id} has no incoming causal links (orphan)."
                )

        return {
            "status": "pass" if not issues else "fail",
            "issues": issues,
            "events_count": len(q_events),
            "hypotheses_count": len(q_hyps),
        }
