"""Adaptive Evidence Pipeline using HindsightAgent multi-agent system.

This pipeline uses managed agents (evidence_collector, causal_analyzer) that can
self-evaluate and iterate to build deep causal graphs instead of rigid stage-by-stage processing.
"""

import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from src.pipelines.evidence.pipeline import EvidencePipeline
from src.pipelines.prompts import HindsightCausalAnalysisPrompts
from src.config.pipeline import EvidencePipelineConfig
from src.config import DatabaseConfig, get_config
from src.domain.models import Question
from src.agents.hindsight_agent import HindsightAgent
from src.utils.logging import logger


class AdaptiveEvidencePipeline(EvidencePipeline):
    """Evidence pipeline using adaptive multi-agent system.

    Differences from base EvidencePipeline:
    - Uses HindsightAgent with managed sub-agents instead of rigid stages
    - Agents can self-evaluate and iterate to improve graph depth
    - More robust - agents adapt when initial attempts fail
    - Produces deeper causal graphs (3+ levels vs 1 level)

    Falls back to base pipeline behavior if agent mode disabled.
    """

    def __init__(
        self,
        evidence_config: EvidencePipelineConfig,
        database_config: DatabaseConfig,
        enable_persistence: bool = True,
        max_concurrent_questions: int = 1,
        min_quality_score: Optional[float] = None,
        use_agents: bool = True,
        agent_max_steps: int = 30,
        min_graph_depth: int = 3,
    ):
        """Initialize adaptive evidence pipeline.

        Args:
            evidence_config: Evidence pipeline configuration
            database_config: Database configuration
            enable_persistence: Whether to persist results to database
            max_concurrent_questions: Maximum concurrent question processing
            min_quality_score: Minimum quality score filter
            use_agents: Whether to use agent-based processing (default: True)
            agent_max_steps: Maximum steps for manager agent (default: 30)
            min_graph_depth: Minimum causal chain depth required (default: 3)
        """
        super().__init__(
            evidence_config,
            database_config,
            enable_persistence,
            max_concurrent_questions,
            min_quality_score,
        )

        self.use_agents = use_agents
        self.agent_max_steps = agent_max_steps
        self.min_graph_depth = min_graph_depth

        # Initialize prompt generator
        self.prompts = HindsightCausalAnalysisPrompts()

        # Agent will be created per-question with context (not here)
        # This ensures proper provenance tracking
        if self.use_agents:
            logger.info("Adaptive multi-agent mode enabled (agents created per-question with provenance context)")

    async def _process_single_question(self, question: Question) -> dict:
        """Process a single question using adaptive agents or fallback to base pipeline.

        Args:
            question: The question to process

        Returns:
            Dictionary with 'evidence_articles', 'causal_hypotheses', and stage results
        """
        if self.use_agents:
            return await self._process_with_agents(question)
        else:
            # Fallback to rigid stage-based processing
            return await super()._process_single_question(question)

    async def _process_with_agents(self, question: Question) -> dict:
        """Process question using HindsightAgent multi-agent system.

        Creates a new agent per question with provenance context, ensuring
        all articles, events, and hypotheses are properly linked to the question.

        Args:
            question: Question to process

        Returns:
            Dictionary with results
        """
        logger.info(f"[AGENT MODE] Processing question: {question.id}")

        # Create agent WITH question context for provenance tracking
        # This ensures all tools know which question they're serving
        hindsight_agent = HindsightAgent(
            db_path=self.database_config.db_path,
            max_steps=self.agent_max_steps,
            question_id=question.id,  # Provenance context
            target_event_id=question.target_event_id,  # Target for causal graph
        )
        logger.debug(f"[{question.id}] Created context-aware HindsightAgent")

        # Construct agent prompt using prompt generator
        prompt = self.prompts.get_agent_prompt(
            question=question,
            min_graph_depth=self.min_graph_depth,
            evidence_window_days=self.evidence_config.evidence_window_days,
            min_evidence_articles=self.evidence_config.min_evidence_articles,
            confidence_threshold=self.evidence_config.causal_confidence_threshold,
        )

        try:
            # Run agent in thread pool to avoid blocking
            logger.debug(f"[{question.id}] Starting HindsightAgent...")
            result = await asyncio.to_thread(hindsight_agent.run, prompt)
            logger.info(f"[{question.id}] Agent completed successfully")

            # Extract results from database (agent persisted everything)
            from src.domain.models import Article, CausalHypothesis
            from src.core.database import GenericDatabase

            db = GenericDatabase(self.database_config.db_path)

            # Get articles and hypotheses for this question
            all_articles = db.get_many(Article)
            all_hypotheses = db.get_many(CausalHypothesis)

            # Filter hypotheses for this question
            question_hypotheses = [
                h for h in all_hypotheses
                if question.id in h.discovered_by_question_ids
            ]

            # Get articles referenced by these hypotheses
            evidence_article_ids = set()
            for hyp in question_hypotheses:
                evidence_article_ids.update(hyp.evidence_article_ids)

            evidence_articles = [a for a in all_articles if a.id in evidence_article_ids]

            logger.info(
                f"[{question.id}] Agent results: "
                f"{len(evidence_articles)} articles, "
                f"{len(question_hypotheses)} hypotheses"
            )

            # Evaluate article quality based on collected evidence articles
            from src.utils.article_analysis import (
                analyze_timeline,
                analyze_sources,
                identify_gaps,
                calculate_quality
            )

            article_quality_score = 0.0
            article_coverage = None

            if evidence_articles:
                # Use comprehensive quality calculation with timeline analysis
                timeline_data = analyze_timeline(evidence_articles, question.resolution_date)
                source_data = analyze_sources(evidence_articles)
                gaps = identify_gaps(timeline_data)
                quality_metrics = calculate_quality(evidence_articles, timeline_data, source_data, gaps)

                article_quality_score = quality_metrics["score"]

                # Structure result for compatibility with existing code
                article_coverage = {
                    "quality": quality_metrics,
                    "article_count": len(evidence_articles),
                    "sources": {"unique_sources": source_data["unique_sources"]},
                    "coverage_end_date": question.resolution_date,
                    "timeline": timeline_data,
                    "gaps": gaps
                }

                logger.info(
                    f"[{question.id}] Article quality: {article_quality_score:.2f} "
                    f"({article_coverage['article_count']} articles, "
                    f"{article_coverage['sources']['unique_sources']} sources, "
                    f"{len(gaps)} time gaps)"
                )
            else:
                logger.warning(f"[{question.id}] No evidence articles collected - article quality: 0.0")

            # Evaluate graph quality using shared utilities
            from src.utils.graph_analysis import calculate_graph_quality

            graph_quality_score = 0.0
            max_depth = 0

            if question_hypotheses:
                # Calculate graph quality using shared utility
                quality_metrics = calculate_graph_quality(
                    hypotheses=question_hypotheses,
                    target_event_id=question.target_event_id,
                    min_depth_for_full_score=self.min_graph_depth
                )

                graph_quality_score = quality_metrics['quality_score']
                max_depth = quality_metrics['max_depth']

                logger.info(
                    f"[{question.id}] Graph quality: {graph_quality_score:.2f} "
                    f"(depth: {max_depth}, events: {quality_metrics['event_count']}, "
                    f"hypotheses: {quality_metrics['hypothesis_count']})"
                )
            else:
                logger.warning(f"[{question.id}] No causal hypotheses generated - graph quality: 0.0")

            # Check if pipeline should be marked as failed based on quality
            status_message = None
            if article_quality_score == 0.0:
                status_message = "Failed: Article quality is zero (no/insufficient articles)"
                logger.error(f"[{question.id}] {status_message}")
            elif graph_quality_score == 0.0:
                status_message = "Failed: Graph quality is zero (no/insufficient causal hypotheses)"
                logger.error(f"[{question.id}] {status_message}")
            elif max_depth < self.min_graph_depth:
                status_message = f"Failed: Graph depth ({max_depth}) below minimum ({self.min_graph_depth})"
                logger.error(f"[{question.id}] {status_message}")

            # If failed, return empty results to signal failure
            if status_message:
                return {
                    "evidence_articles": [],
                    "causal_hypotheses": [],
                    "stage_results": [],
                    "agent_output": result,
                    "status": "failed",
                    "failure_reason": status_message,
                    "article_quality": article_quality_score,
                    "graph_quality": graph_quality_score,
                    "graph_depth": max_depth
                }

            # Success
            return {
                "evidence_articles": evidence_articles,
                "causal_hypotheses": question_hypotheses,
                "stage_results": [],  # Agent mode doesn't have stages
                "agent_output": result,
                "status": "success",
                "article_quality": article_quality_score,
                "graph_quality": graph_quality_score,
                "graph_depth": max_depth
            }

        except Exception as e:
            logger.error(f"[{question.id}] Agent processing failed: {e}")
            logger.warning(f"[{question.id}] Falling back to rigid pipeline")

            # Fallback to base pipeline on error
            return await super()._process_single_question(question)

    def get_summary(self) -> Dict[str, Any]:
        """Get pipeline execution summary with agent-specific info.

        Returns:
            Dictionary with summary statistics
        """
        summary = super().get_summary()

        # Add agent-specific info
        if self.use_agents:
            summary['processing_mode'] = 'adaptive_agents'
            summary['agent_max_steps'] = self.agent_max_steps
            summary['min_graph_depth'] = self.min_graph_depth
        else:
            summary['processing_mode'] = 'rigid_stages'

        return summary
