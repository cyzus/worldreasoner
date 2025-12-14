"""Unified pipeline execution with progress callbacks.

This module provides a common interface for running all pipeline types,
with support for progress tracking, error handling, and result collection.
"""

from typing import List, Optional, Callable, Dict, Any
from dataclasses import dataclass
from enum import Enum
import asyncio
import time
from datetime import datetime, timezone

from src.config import get_config, Config
from src.config.pipeline import EvidencePipelineConfig
from src.config import DatabaseConfig
from src.core.database import GenericDatabase
from src.domain.models import Question, Forecast, Article, CausalHypothesis, Event
from src.pipelines.base import PipelineStageStatus
from src.utils.logging import logger


class PipelineType(Enum):
    """Available pipeline types."""
    COLLECTION = "collection"
    EVIDENCE = "evidence"
    ADAPTIVE_EVIDENCE = "adaptive_evidence"
    FORECAST = "forecast"
    EVALUATION = "evaluation"
    BENCHMARK = "benchmark"


@dataclass
class PipelineProgress:
    """Progress update from pipeline execution."""
    current: int
    total: int
    question_id: Optional[str]
    stage: str
    message: str


@dataclass
class PipelineResult:
    """Result of pipeline execution."""
    processed: List[Dict[str, Any]]
    failed: List[Dict[str, Any]]
    skipped: List[Dict[str, Any]]
    duration_seconds: float

    @property
    def success_count(self) -> int:
        return len(self.processed)

    @property
    def failure_count(self) -> int:
        return len(self.failed)

    @property
    def skip_count(self) -> int:
        return len(self.skipped)


class PipelineRunner:
    """Unified pipeline execution with progress callbacks.

    This class provides a common interface for running all pipeline types,
    with support for progress tracking, error handling, and result collection.

    Usage:
        runner = PipelineRunner(db_path="worldreasoner.db")
        
        # With progress callback
        def on_progress(p: PipelineProgress):
            print(f"[{p.current}/{p.total}] {p.stage}: {p.message}")
        
        result = await runner.run(
            PipelineType.EVIDENCE,
            question_ids=["q_1", "q_2"],
            on_progress=on_progress
        )
    """

    def __init__(
        self,
        db_path: str = "worldreasoner.db",
        config: Optional[Config] = None,
    ):
        self.db_path = db_path
        self.config = config or get_config()
        self.db = GenericDatabase(db_path)

    async def run(
        self,
        pipeline_type: PipelineType,
        question_ids: List[str],
        on_progress: Optional[Callable[[PipelineProgress], None]] = None,
        **kwargs
    ) -> PipelineResult:
        """Run a pipeline on selected questions.

        Args:
            pipeline_type: Type of pipeline to run
            question_ids: List of question IDs to process
            on_progress: Optional callback for progress updates
            **kwargs: Pipeline-specific configuration

        Returns:
            PipelineResult with processed/failed/skipped items
        """
        start_time = time.time()

        if pipeline_type == PipelineType.COLLECTION:
            logger.info(f"Starting {pipeline_type.value} pipeline")
            result = await self._run_collection(on_progress, **kwargs)
        else:
            logger.info(f"Starting {pipeline_type.value} pipeline for {len(question_ids)} questions")
            
            if pipeline_type == PipelineType.EVIDENCE:
                result = await self._run_evidence(question_ids, on_progress, **kwargs)
            elif pipeline_type == PipelineType.ADAPTIVE_EVIDENCE:
                result = await self._run_adaptive_evidence(question_ids, on_progress, **kwargs)
            elif pipeline_type == PipelineType.FORECAST:
                result = await self._run_forecast(question_ids, on_progress, **kwargs)
            elif pipeline_type == PipelineType.EVALUATION:
                result = await self._run_evaluation(question_ids, on_progress, **kwargs)
            elif pipeline_type == PipelineType.BENCHMARK:
                result = await self._run_benchmark(question_ids, on_progress, **kwargs)
            else:
                raise ValueError(f"Unknown pipeline type: {pipeline_type}")

        result.duration_seconds = time.time() - start_time
        
        logger.info(
            f"Pipeline completed in {result.duration_seconds:.1f}s: "
            f"{result.success_count} succeeded, {result.failure_count} failed, "
            f"{result.skip_count} skipped"
        )
        
        return result

    async def _run_collection(
        self,
        on_progress: Optional[Callable],
        goal_path: str,
        sources_config: str = "config/sources.yaml",
        enable_polymarket: bool = True,
        enable_news: bool = True,
        parallel_sources: bool = True,
        skip_indexing: bool = False,
        **kwargs
    ) -> PipelineResult:
        """Run goal-oriented question collection pipeline."""
        from datetime import timedelta
        from src.config.collection_goal import CollectionGoal
        from src.pipelines.question.orchestrator import (
            QuestionCollectionOrchestrator,
            OrchestratorConfig,
        )
        from src.pipelines.question.sources.markets import PolymarketRunner
        from src.pipelines.question.sources.news import NewsBasedRunner
        from src.pipelines.stages import ArticleCollectionConfig, EventIdentificationConfig, ArticleSource
        from src.config.pipeline import QuestionPipelineConfig
        from src.utils.search_indexing import auto_index_articles
        import yaml

        results = PipelineResult([], [], [], 0.0)

        try:
            # Load collection goal
            if on_progress:
                on_progress(PipelineProgress(
                    current=1,
                    total=5,
                    question_id=None,
                    stage="collection",
                    message="Loading collection goal"
                ))

            goal = CollectionGoal.from_yaml(goal_path)
            goal.validate_distributions()

            # Initialize database tables
            self.db.create_table(Question)
            self.db.create_table(Article)
            self.db.create_table(Event)
            self.db.create_table(CausalHypothesis)

            # Initialize sources
            if on_progress:
                on_progress(PipelineProgress(
                    current=2,
                    total=5,
                    question_id=None,
                    stage="collection",
                    message="Initializing sources"
                ))

            sources = {}

            # Polymarket source
            if enable_polymarket:
                sources["polymarket"] = PolymarketRunner(
                    min_volume_usd=0.0,
                    require_ground_truth=goal.require_ground_truth,
                )

            # News-based source
            if enable_news:
                with open(sources_config, 'r') as f:
                    sources_data = yaml.safe_load(f)

                article_sources = [ArticleSource(**s) for s in sources_data.get('sources', [])]
                domains = [cat for cat in goal.category_distribution.keys() if cat != "other"]

                article_config = ArticleCollectionConfig(
                    sources=article_sources,
                    start_date=datetime.now(timezone.utc) - timedelta(days=abs(goal.quality.min_resolution_days)),
                    end_date=datetime.now(timezone.utc),
                    domains=domains,
                )

                event_config = EventIdentificationConfig()

                question_config = QuestionPipelineConfig(
                    max_questions=goal.total_questions,
                    domains=list(goal.category_distribution.keys()),
                    question_types=list(goal.type_distribution.keys()),
                    require_ground_truth=goal.require_ground_truth,
                )

                sources["news"] = NewsBasedRunner(
                    article_config=article_config,
                    event_config=event_config,
                    question_config=question_config,
                    db_path=self.db_path,
                )

            if not sources:
                results.failed.append({"error": "No sources enabled"})
                return results

            # Configure orchestrator
            if on_progress:
                on_progress(PipelineProgress(
                    current=3,
                    total=5,
                    question_id=None,
                    stage="collection",
                    message="Starting orchestration"
                ))

            orchestrator_config = OrchestratorConfig(
                max_iterations=1,  # Allow multiple iterations to meet goal
                parallel_sources=parallel_sources,
                save_intermediate_results=True,
            )

            orchestrator = QuestionCollectionOrchestrator(
                goal=goal,
                sources=sources,
                config=orchestrator_config,
                db_path=self.db_path,
            )

            # Run collection
            collection_result = await orchestrator.collect_until_goal_met()

            if on_progress:
                on_progress(PipelineProgress(
                    current=4,
                    total=5,
                    question_id=None,
                    stage="collection",
                    message=f"Collected {len(collection_result.questions)} questions"
                ))

            # Auto-index articles if not skipped
            if not skip_indexing:
                if on_progress:
                    on_progress(PipelineProgress(
                        current=5,
                        total=5,
                        question_id=None,
                        stage="collection",
                        message="Indexing articles"
                    ))
                await auto_index_articles(db_path=self.db_path)

            # Convert to standard result format
            for q in collection_result.questions:
                results.processed.append({
                    "id": q.id,
                    "text": q.question_text,
                    "type": str(q.question_type),
                    "domain": str(q.domain),
                    "source": q.source,
                })

            if collection_result.errors:
                for error in collection_result.errors:
                    results.failed.append({"error": str(error)})

            # Store collection metadata
            results.processed.append({
                "goal_met": collection_result.goal_met,
                "iterations": collection_result.iterations,
                "by_source": dict(collection_result.progress.by_source) if collection_result.progress.by_source else {},
                "by_type": dict(collection_result.progress.by_type) if collection_result.progress.by_type else {},
                "by_category": dict(collection_result.progress.by_category) if collection_result.progress.by_category else {},
            })

        except Exception as e:
            logger.error(f"Collection pipeline failed: {e}")
            results.failed.append({"error": str(e)})

        return results

    async def _run_evidence(
        self,
        question_ids: List[str],
        on_progress: Optional[Callable],
        force_reprocess: bool = False,
        evidence_window_days: int = 365,
        min_evidence_articles: int = 5,
        skip_indexing: bool = False,
        **kwargs
    ) -> PipelineResult:
        """Run basic evidence pipeline."""
        from src.pipelines.evidence import EvidencePipeline

        # Configure pipeline
        evidence_config = EvidencePipelineConfig(
            evidence_window_days=evidence_window_days,
            min_evidence_articles=min_evidence_articles,
            include_expert_analysis=True,
        )
        
        database_config = DatabaseConfig(db_path=self.db_path)

        pipeline = EvidencePipeline(
            evidence_config=evidence_config,
            database_config=database_config,
            enable_persistence=True,
        )

        results = PipelineResult([], [], [], 0.0)

        for i, qid in enumerate(question_ids):
            try:
                # Send progress update
                if on_progress:
                    on_progress(PipelineProgress(
                        current=i + 1,
                        total=len(question_ids),
                        question_id=qid,
                        stage="evidence",
                        message=f"Processing question {qid}"
                    ))

                # Check if already has evidence (unless force reprocess)
                question = self.db.get(Question, qid)
                if not question:
                    results.failed.append({"id": qid, "error": "Question not found"})
                    continue

                if not force_reprocess:
                    # Check if evidence already exists
                    all_hypotheses = self.db.get_many(CausalHypothesis)
                    hypotheses = [h for h in all_hypotheses if qid in h.discovered_by_question_ids]
                    if hypotheses:
                        logger.info(f"Question {qid} already has {len(hypotheses)} hypotheses, skipping")
                        results.skipped.append({
                            "id": qid,
                            "reason": f"Already has {len(hypotheses)} hypotheses"
                        })
                        continue

                # Run pipeline on single question
                logger.info(f"Running evidence pipeline on question: {qid}")
                pipeline_results = await pipeline.run([question])

                # Check if pipeline succeeded (no FAILED stages and at least one result)
                has_failure = any(r.status == PipelineStageStatus.FAILED for r in pipeline_results)

                if pipeline_results and not has_failure:
                    # Count generated artifacts
                    articles = self.db.get_many(Article, filters={"collected_for_question_id": qid})
                    all_hypotheses = self.db.get_many(CausalHypothesis)
                    hypotheses = [h for h in all_hypotheses if qid in h.discovered_by_question_ids]

                    results.processed.append({
                        "id": qid,
                        "articles": len(articles),
                        "hypotheses": len(hypotheses),
                    })
                    logger.info(f"Successfully processed {qid}: {len(articles)} articles, {len(hypotheses)} hypotheses")
                else:
                    # Find error message from failed stages
                    error_msgs = [r.error_message for r in pipeline_results if r.error_message]
                    error_msg = "; ".join(error_msgs) if error_msgs else "Pipeline failed with no error message"
                    results.failed.append({"id": qid, "error": error_msg})
                    logger.error(f"Failed to process {qid}: {error_msg}")

            except Exception as e:
                logger.error(f"Error processing question {qid}: {e}")
                results.failed.append({"id": qid, "error": str(e)})

        # Auto-index articles if not skipped
        if not skip_indexing:
            from src.utils.search_indexing import auto_index_articles

            try:
                logger.info("Indexing articles for hybrid search...")
                index_stats = await auto_index_articles(db_path=self.db_path)
                if index_stats['status'] == 'success':
                    logger.info(f"Indexed {index_stats['newly_indexed']} new articles (total: {index_stats['final_indexed']})")
                elif index_stats['status'] == 'up_to_date':
                    logger.info("Search index is up to date")
                elif index_stats['status'] == 'no_articles':
                    logger.warning("No articles to index")
                else:
                    logger.error(f"Indexing failed: {index_stats.get('error', 'Unknown error')}")
            except Exception as e:
                logger.error(f"Failed to auto-index articles: {e}")

        return results

    async def _run_adaptive_evidence(
        self,
        question_ids: List[str],
        on_progress: Optional[Callable],
        agent_max_steps: int = 30,
        min_graph_depth: int = 3,
        skip_indexing: bool = False,
        **kwargs
    ) -> PipelineResult:
        """Run adaptive multi-agent evidence pipeline."""
        from src.pipelines.evidence.adaptive_pipeline import AdaptiveEvidencePipeline

        evidence_config = EvidencePipelineConfig()
        database_config = DatabaseConfig(db_path=self.db_path)

        pipeline = AdaptiveEvidencePipeline(
            evidence_config=evidence_config,
            database_config=database_config,
            enable_persistence=True,
            agent_max_steps=agent_max_steps,
            min_graph_depth=min_graph_depth,
        )

        results = PipelineResult([], [], [], 0.0)

        for i, qid in enumerate(question_ids):
            try:
                if on_progress:
                    on_progress(PipelineProgress(
                        current=i + 1,
                        total=len(question_ids),
                        question_id=qid,
                        stage="adaptive_evidence",
                        message=f"Deep analysis of question {qid}"
                    ))

                question = self.db.get(Question, qid)
                if not question:
                    results.failed.append({"id": qid, "error": "Question not found"})
                    continue

                logger.info(f"Running adaptive evidence pipeline on question: {qid}")
                pipeline_results = await pipeline.run([question])

                logger.info(f"Pipeline returned {len(pipeline_results)} results")
                for r in pipeline_results:
                    logger.info(f"  Stage: {r.stage_name}, Status: {r.status}, Error: {r.error_message}")

                # Check if pipeline succeeded (no FAILED stages and at least one result)
                has_failure = any(r.status == PipelineStageStatus.FAILED for r in pipeline_results)

                if pipeline_results and not has_failure:
                    all_hypotheses = self.db.get_many(CausalHypothesis)
                    hypotheses = [h for h in all_hypotheses if qid in h.discovered_by_question_ids]
                    results.processed.append({
                        "id": qid,
                        "hypotheses": len(hypotheses),
                    })
                else:
                    # Find error message from failed stages
                    error_msgs = [r.error_message for r in pipeline_results if r.error_message]
                    error_msg = "; ".join(error_msgs) if error_msgs else "Pipeline failed with no error message"
                    results.failed.append({"id": qid, "error": error_msg})

            except Exception as e:
                logger.error(f"Error processing question {qid}: {e}")
                results.failed.append({"id": qid, "error": str(e)})

        # Auto-index articles if not skipped
        if not skip_indexing:
            from src.utils.search_indexing import auto_index_articles

            try:
                logger.info("Indexing articles for hybrid search...")
                index_stats = await auto_index_articles(db_path=self.db_path)
                if index_stats['status'] == 'success':
                    logger.info(f"Indexed {index_stats['newly_indexed']} new articles (total: {index_stats['final_indexed']})")
                elif index_stats['status'] == 'up_to_date':
                    logger.info("Search index is up to date")
                elif index_stats['status'] == 'no_articles':
                    logger.warning("No articles to index")
                else:
                    logger.error(f"Indexing failed: {index_stats.get('error', 'Unknown error')}")
            except Exception as e:
                logger.error(f"Failed to auto-index articles: {e}")

        return results

    async def _run_forecast(
        self,
        question_ids: List[str],
        on_progress: Optional[Callable],
        model: Optional[str] = None,
        offset_days: int = 7,
        knowledge_only: bool = False,
        min_context_items: int = 3,
        **kwargs
    ) -> PipelineResult:
        """Run forecasting on questions."""
        from src.agents.forecast_agent import ForecastAgent
        from src.utils.llm_utils import get_knowledge_cutoff_date

        results = PipelineResult([], [], [], 0.0)

        # Override config model if specified
        config = self.config
        if model:
            # Create a copy of config with the specified model
            from copy import deepcopy
            config = deepcopy(self.config)
            config.llm.model = model

        for i, qid in enumerate(question_ids):
            try:
                if on_progress:
                    on_progress(PipelineProgress(
                        current=i + 1,
                        total=len(question_ids),
                        question_id=qid,
                        stage="forecast",
                        message=f"Forecasting on question {qid}"
                    ))

                question = self.db.get(Question, qid)
                if not question:
                    results.failed.append({"id": qid, "error": "Question not found"})
                    continue

                logger.info(f"Running forecast on question: {qid}")

                # Determine simulated date and knowledge cutoff
                forecast_setup = question.prepare_forecast(
                    db=self.db,
                    offset_days_before_resolution=offset_days,
                    min_context_items=min_context_items
                )



                # Create forecast agent with correct parameters
                agent = ForecastAgent(
                    question=question,
                    simulated_date=forecast_setup['simulated_date'].isoformat(),
                    knowledge_cutoff=get_knowledge_cutoff_date(config.llm.model),
                    config=config,
                    db_path=self.db_path,  # Pass database path for per-request switching
                    knowledge_only=knowledge_only,
                )

                # Run agent to generate forecast
                result = agent.run(
                    f"Forecast the outcome of this question. Use get_question to see the details, "
                    f"research if needed (unless knowledge-only mode), then submit your forecast."
                )

                # The forecast should be submitted via the MCP tool and saved to DB
                # Check if forecast was created
                forecasts = self.db.get_many(Forecast, filters={"question_id": qid})
                
                if forecasts:
                    # Get the most recent forecast (using timestamp instead of created_at)
                    latest_forecast = sorted(forecasts, key=lambda f: f.timestamp, reverse=True)[0]
                    results.processed.append({
                        "id": qid,
                        "forecast_id": latest_forecast.id,
                        "prediction": latest_forecast.prediction,
                        "confidence": latest_forecast.confidence,
                    })
                    logger.info(f"Successfully forecast {qid}: {latest_forecast.prediction} (confidence: {latest_forecast.confidence})")
                else:
                    results.failed.append({"id": qid, "error": "No forecast was created"})

            except Exception as e:
                logger.error(f"Error forecasting question {qid}: {e}")
                results.failed.append({"id": qid, "error": str(e)})

        return results

    async def _run_evaluation(
        self,
        question_ids: List[str],
        on_progress: Optional[Callable],
        **kwargs
    ) -> PipelineResult:
        """Run evaluation on existing forecasts."""
        from src.domain.evaluation import ForecastEvaluator

        evaluator = ForecastEvaluator()
        results = PipelineResult([], [], [], 0.0)

        for i, qid in enumerate(question_ids):
            try:
                if on_progress:
                    on_progress(PipelineProgress(
                        current=i + 1,
                        total=len(question_ids),
                        question_id=qid,
                        stage="evaluation",
                        message=f"Evaluating forecasts for question {qid}"
                    ))

                question = self.db.get(Question, qid)
                if not question:
                    results.failed.append({"id": qid, "error": "Question not found"})
                    continue

                # Get forecasts for this question
                forecasts = self.db.get_many(Forecast, filters={"question_id": qid})
                
                if not forecasts:
                    results.skipped.append({"id": qid, "reason": "No forecasts found"})
                    continue

                logger.info(f"Evaluating {len(forecasts)} forecasts for question: {qid}")

                evaluated_count = 0
                for forecast in forecasts:
                    evaluation = evaluator.evaluate(forecast, question)
                    if evaluation:
                        # Save evaluation metrics back to forecast
                        forecast.evaluation = evaluation.dict()
                        self.db.save(Forecast, forecast)
                        evaluated_count += 1

                results.processed.append({
                    "id": qid,
                    "forecasts_evaluated": evaluated_count,
                })

            except Exception as e:
                logger.error(f"Error evaluating question {qid}: {e}")
                results.failed.append({"id": qid, "error": str(e)})

        return results

    async def _run_benchmark(
        self,
        question_ids: List[str],
        on_progress: Optional[Callable],
        **kwargs
    ) -> PipelineResult:
        """Run benchmark (forecast + evaluate) on questions."""
        # First forecast
        forecast_result = await self._run_forecast(
            question_ids, on_progress, **kwargs
        )

        # Only evaluate successfully forecasted questions
        successful_ids = [r["id"] for r in forecast_result.processed]

        eval_result = await self._run_evaluation(
            successful_ids, on_progress, **kwargs
        )

        return PipelineResult(
            processed=eval_result.processed,
            failed=forecast_result.failed + eval_result.failed,
            skipped=forecast_result.skipped + eval_result.skipped,
            duration_seconds=0.0,
        )

    async def clear_evidence(
        self,
        question_ids: List[str],
        cascade: bool = True,
    ) -> Dict[str, List[str]]:
        """Clear evidence data for questions.

        Args:
            question_ids: Questions to clear evidence for
            cascade: Also delete orphaned events/articles

        Returns:
            Dict with cleared/failed lists
        """
        from src.cli.core.question_manager import QuestionManager

        manager = QuestionManager(self.db)
        results = {"cleared": [], "failed": []}

        for qid in question_ids:
            try:
                manager.clear_evidence(qid, cascade=cascade, dry_run=False)
                results["cleared"].append(qid)
            except Exception as e:
                logger.error(f"Failed to clear evidence for {qid}: {e}")
                results["failed"].append({"id": qid, "error": str(e)})

        return results
