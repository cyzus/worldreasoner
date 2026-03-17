"""Graph Builder pipeline for asynchronous background processing."""

from typing import Dict, Any, List, Optional

from src.config import get_config
from src.core.database import GenericDatabase
from src.domain.models import Event, Question
from src.agents.graph_builder_agent import GraphBuilderAgentFactory
from src.pipelines.prompts import graph_builder as graph_builder_prompts
from src.config.pipeline import SATISFACTION_DEFAULTS
from src.services.question_monitor_service import QuestionMonitorService
from src.utils.logging import logger


class GraphBuilderPipeline:
    """Pipeline for converting causal explanations into structured graphs."""

    def __init__(
        self,
        db_path: str,
        model_id: Optional[str] = None,
        temperature: float = 0.2,
        min_graph_depth: int = SATISFACTION_DEFAULTS.min_graph_depth,
        min_events: int = SATISFACTION_DEFAULTS.min_graph_events,
    ):
        """Initialize the pipeline."""
        self.db_path = db_path
        self.db = GenericDatabase(db_path)
        self.model_id = model_id or get_config().llm.model
        self.temperature = temperature
        self.min_graph_depth = min_graph_depth
        self.min_events = min_events

    def _load_pending_questions(self) -> List[Question]:
        """Find graph-eligible questions waiting for graph building."""
        all_questions = self.db.get_many(Question)
        pending = [q for q in all_questions if q.causal_explanation and not q.graph_built]
        monitor = QuestionMonitorService(self.db)
        eligible = [q for q in pending if monitor.has_evidence_articles(q.id)]

        skipped = len(pending) - len(eligible)
        if skipped > 0:
            logger.info(
                f"Skipping {skipped} pending question(s) with no collected articles."
            )

        return eligible

    def process_pending(self, limit: int = 10) -> Dict[str, Any]:
        """Process all pending questions."""
        pending = self._load_pending_questions()
        if not pending:
            logger.info("No questions waiting for graph building.")
            return {"processed": 0, "success": 0, "failed": 0}

        pending = pending[:limit]
        logger.info(f"Found {len(pending)} pending questions for graph building.")

        results = {"processed": 0, "success": 0, "failed": 0}

        for q in pending:
            logger.info(f"Building graph for question {q.id}...")
            success = self._process_single_question(q)
            results["processed"] += 1
            if success:
                results["success"] += 1
            else:
                results["failed"] += 1

        return results

    def _process_single_question(self, question: Question) -> bool:
        """Process a single question's graph."""
        try:
            monitor = QuestionMonitorService(self.db)
            if not monitor.has_evidence_articles(question.id):
                reason = (
                    "No evidence articles found for this question "
                    "(collected_for_question_id / related_question_ids). "
                    "Run `wr evidence run` first."
                )
                logger.warning(f"Skipping graph build for {question.id}: {reason}")
                question.graph_build_error = reason
                self.db.save(Question, question)
                return False

            # 1. Find actual outcome event
            events = self.db.get_many(Event)
            actual_outcome_id = "unknown"

            # Use explicit fallback
            outcome_events = []
            if getattr(question, "outcome_event_ids", None):
                outcome_events = [
                    e for e in events if e.id in question.outcome_event_ids
                ]
            else:
                outcome_events = [
                    e
                    for e in events
                    if getattr(e, "extracted_for_question_id", None) == question.id
                    and getattr(e, "is_outcome", False)
                ]

            for e in outcome_events:
                if getattr(e, "is_actual_outcome", False):
                    actual_outcome_id = e.id
                    break

            if actual_outcome_id == "unknown":
                logger.warning(
                    f"Question {question.id} lacks an actual outcome event! Agent will struggle."
                )

            # 2. Build Prompt
            prompt = graph_builder_prompts.get_prompt(
                question=question,
                actual_outcome_event_id=actual_outcome_id,
                min_graph_depth=self.min_graph_depth,
                min_events=self.min_events,
            )

            # 3. Create Agent
            agent = GraphBuilderAgentFactory.create(
                model_id=self.model_id,
                temperature=self.temperature,
                db_path=self.db_path,
                question_id=question.id,
            )

            # 4. Run Agent
            logger.info(f"Starting GraphBuilderAgent for Q: {question.id}")
            _ = agent.run(prompt)

            # Refresh question from DB to check if tool marked it success
            refreshed_q = self.db.get(Question, question.id)
            if not refreshed_q.graph_built:
                logger.error(
                    f"Agent finished but graph_built is still False for Q: {question.id}"
                )
                return False

            # Independently verify the graph meets requirements
            monitor = QuestionMonitorService(self.db)
            graph_sat = monitor.check_graph_satisfaction(question.id)
            if not graph_sat.is_satisfied:
                reason = f"Graph requirements not met: {graph_sat.missing_requirements}"
                logger.error(f"[{question.id}] {reason}")
                refreshed_q.graph_built = False
                refreshed_q.graph_build_error = reason
                self.db.save(Question, refreshed_q)
                return False

            logger.info(f"Successfully built graph for Q: {question.id}")
            return True

        except Exception as e:
            logger.error(f"Failed to process graph for {question.id}: {str(e)}")
            question.graph_build_error = str(e)
            self.db.save(Question, question)
            return False
