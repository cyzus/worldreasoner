"""Pipeline execution service with progress tracking.

Extracted from src/cli/core/pipeline_runner.py to enable reuse
across CLI and backend API without CLI dependencies.
"""

import asyncio
import time
from copy import deepcopy
from typing import List, Optional, Callable, Dict, Any
from datetime import datetime, timezone

from src.config import Config, get_config
from src.config.pipeline import EvidencePipelineConfig
from src.config import DatabaseConfig
from src.core.database import GenericDatabase
from src.domain.models import Question, Forecast, Article, CausalHypothesis, Event
from src.pipelines.base import PipelineStageStatus
from src.config.pipeline import SATISFACTION_DEFAULTS
from src.pipelines.types import PipelineProgress, PipelineResult, PipelineType
from src.utils.logging import logger


# Unified per-pipeline question concurrency limit (evidence/adaptive_evidence/graph_builder).
PIPELINE_QUESTION_CONCURRENCY_LIMIT = 5


class PipelineExecutor:
    """Service for executing pipelines with progress tracking."""

    def __init__(
        self, config: Optional[Config] = None, db_path: str = "worldreasoner.db"
    ):
        self.config = config or get_config()
        self.db_path = db_path
        self.db = GenericDatabase(db_path)

    async def execute(
        self,
        pipeline_type: PipelineType,
        question_ids: List[str],
        on_progress: Optional[Callable[[PipelineProgress], None]] = None,
        **kwargs,
    ) -> PipelineResult:
        """Execute a pipeline on selected questions.

        Args:
            pipeline_type: Type of pipeline to run
            question_ids: List of question IDs to process
            on_progress: Optional callback for progress updates
            **kwargs: Pipeline-specific configuration

        Returns:
            PipelineResult with processed/failed/skipped items
        """
        start_time = time.time()
        logger.info(f"Starting {pipeline_type.value} pipeline")

        if pipeline_type == PipelineType.COLLECTION:
            result = await self._run_collection(on_progress, **kwargs)
        elif pipeline_type == PipelineType.NEWS_COLLECTION:
            result = await self._run_news_collection(
                on_progress, collection_config=kwargs
            )
        elif pipeline_type == PipelineType.EVIDENCE:
            result = await self._run_evidence(question_ids, on_progress, **kwargs)
        elif pipeline_type == PipelineType.ADAPTIVE_EVIDENCE:
            result = await self._run_adaptive_evidence(
                question_ids, on_progress, **kwargs
            )
        elif pipeline_type == PipelineType.FORECAST:
            result = await self._run_forecast(question_ids, on_progress, **kwargs)
        elif pipeline_type == PipelineType.EVALUATION:
            result = await self._run_evaluation(question_ids, on_progress, **kwargs)
        elif pipeline_type == PipelineType.BENCHMARK:
            result = await self._run_benchmark(question_ids, on_progress, **kwargs)
        elif pipeline_type == PipelineType.AUTO_BENCHMARK:
            result = await self._run_auto_benchmark(question_ids, on_progress, **kwargs)
        elif pipeline_type == PipelineType.GRAPH_BUILDER:
            result = await self._run_graph_builder(question_ids, on_progress, **kwargs)
        elif pipeline_type == PipelineType.REASONING_EVAL:
            result = await self._run_reasoning_eval(on_progress, **kwargs)
        else:
            raise ValueError(f"Unknown pipeline type: {pipeline_type}")

        result.duration_seconds = time.time() - start_time

        logger.info(
            f"Pipeline completed in {result.duration_seconds:.1f}s: "
            f"{result.success_count} succeeded, {result.failure_count} failed, "
            f"{result.skip_count} skipped"
        )

        return result

    def _load_article_sources(
        self,
        sources_config: str = "config/sources.yaml",
        domains: Optional[List[str]] = None,
    ):
        """Helper to load and filter article sources."""
        from src.pipelines.collection import ArticleSource
        import yaml

        with open(sources_config, "r") as f:
            sources_data = yaml.safe_load(f)

        article_sources = [ArticleSource(**s) for s in sources_data.get("sources", [])]

        if domains:
            article_sources = [s for s in article_sources if s.domain in domains]

        return article_sources

    def _create_news_runner(
        self,
        article_sources: List[Any],
        domains: List[str],
        question_types: Optional[List[str]] = None,
        max_articles_per_source: int = 3,
        days_back: int = 7,
    ):
        """Helper to create configured NewsBasedRunner."""
        from datetime import timedelta
        from src.pipelines.collection import NewsBasedRunner, ArticleCollectionConfig
        from src.config.pipeline import QuestionPipelineConfig

        article_config = ArticleCollectionConfig(
            sources=article_sources,
            start_date=datetime.now(timezone.utc) - timedelta(days=days_back),
            end_date=datetime.now(timezone.utc),
            domains=domains,
            max_articles_per_source=max_articles_per_source,
        )

        question_config = QuestionPipelineConfig(
            question_types=question_types or [], require_ground_truth=True
        )

        return NewsBasedRunner(
            article_config=article_config,
            question_config=question_config,
            db_path=self.db_path,
        )

    def _check_sufficient_evidence(self, question: Question) -> Optional[str]:
        """Check if a question already has completed evidence.

        Delegates to QuestionMonitorService as the single source of truth.
        Returns a skip-reason string if complete, None if processing is needed.
        """
        from src.services.question_monitor_service import QuestionMonitorService

        satisfaction = QuestionMonitorService(self.db).check_satisfaction(question.id)
        if satisfaction.is_satisfied:
            logger.info(
                f"Question {question.id} already has sufficient evidence "
                f"({satisfaction.article_count} articles, causal_explanation present), skipping"
            )
            return f"Already has sufficient evidence ({satisfaction.article_count} articles)"
        return None

    async def _auto_index_articles(self) -> None:
        """Auto-index articles for hybrid search, logging status."""
        from src.core.search_indexing import auto_index_articles

        try:
            logger.info("Indexing articles for hybrid search...")
            index_stats = await auto_index_articles(db_path=self.db_path, fts_only=True)
            if index_stats["status"] == "success":
                logger.info(
                    f"Indexed {index_stats['newly_indexed']} new articles "
                    f"(total: {index_stats['final_indexed']})"
                )
            elif index_stats["status"] == "up_to_date":
                logger.info("Search index is up to date")
            elif index_stats["status"] == "no_articles":
                logger.warning("No articles to index")
            else:
                logger.error(
                    f"Indexing failed: {index_stats.get('error', 'Unknown error')}"
                )
        except Exception as e:
            logger.error(f"Failed to auto-index articles: {e}")

    def _pipeline_error_message(self, pipeline_results: List) -> str:
        """Extract a combined error message from failed pipeline stage results."""
        msgs = [r.error_message for r in pipeline_results if r.error_message]
        return "; ".join(msgs) if msgs else "Pipeline failed with no error message"

    async def _run_collection(
        self,
        on_progress: Optional[Callable],
        goal_path: str,
        sources_config: str = "config/sources.yaml",
        enable_polymarket: bool = True,
        enable_news: bool = True,
        parallel_sources: bool = True,
        skip_indexing: bool = False,
        **kwargs,
    ) -> PipelineResult:
        """Run goal-oriented question collection pipeline."""
        from src.config.collection_goal import CollectionGoal
        from src.pipelines.collection import (
            QuestionCollectionOrchestrator,
            OrchestratorConfig,
            PolymarketRunner,
        )

        results = PipelineResult([], [], [], 0.0)

        try:
            # Load collection goal
            if on_progress:
                on_progress(
                    PipelineProgress(
                        current=1,
                        total=5,
                        question_id=None,
                        stage="collection",
                        message="Loading collection goal",
                    )
                )

            goal = CollectionGoal.from_yaml(goal_path)
            goal.validate_distributions()

            # Initialize database tables
            self.db.create_table(Question)
            self.db.create_table(Article)
            self.db.create_table(Event)
            self.db.create_table(CausalHypothesis)

            # Initialize sources
            if on_progress:
                on_progress(
                    PipelineProgress(
                        current=2,
                        total=5,
                        question_id=None,
                        stage="collection",
                        message="Initializing sources",
                    )
                )

            sources = {}

            # Polymarket source
            if enable_polymarket:
                sources["polymarket"] = PolymarketRunner(
                    min_volume_usd=0.0,
                    require_ground_truth=goal.require_ground_truth,
                )

            # News-based source
            if enable_news:
                domains = [
                    cat for cat in goal.category_distribution.keys() if cat != "other"
                ]
                article_sources = self._load_article_sources(sources_config, domains)

                # Use slightly different config for goal-based collection (full days back from goal)
                sources["news"] = self._create_news_runner(
                    article_sources=article_sources,
                    domains=domains,
                    question_types=list(goal.type_distribution.keys()),
                    days_back=abs(goal.quality.min_resolution_days),
                    max_articles_per_source=10,  # Higher limit for goal-based
                )
                # Override require_ground_truth for goal-based to match goal
                sources[
                    "news"
                ].question_config.require_ground_truth = goal.require_ground_truth

            if not sources:
                results.failed.append({"error": "No sources enabled"})
                return results

            # Configure orchestrator
            if on_progress:
                on_progress(
                    PipelineProgress(
                        current=3,
                        total=5,
                        question_id=None,
                        stage="collection",
                        message="Starting orchestration",
                    )
                )

            orchestrator_config = OrchestratorConfig(
                max_iterations=1,  # Single broad pass; orchestrator loop handles retries internally
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
                on_progress(
                    PipelineProgress(
                        current=4,
                        total=5,
                        question_id=None,
                        stage="collection",
                        message=f"Collected {len(collection_result.questions)} questions",
                    )
                )

            # Auto-index articles if not skipped
            if not skip_indexing:
                if on_progress:
                    on_progress(
                        PipelineProgress(
                            current=5,
                            total=5,
                            question_id=None,
                            stage="collection",
                            message="Indexing articles",
                        )
                    )
                await self._auto_index_articles()

            # Convert to standard result format
            for q in collection_result.questions:
                results.processed.append(
                    {
                        "id": q.id,
                        "text": q.question_text,
                        "type": str(q.question_type),
                        "domain": str(q.domain),
                        "source": q.source,
                    }
                )

            if collection_result.errors:
                for error in collection_result.errors:
                    results.failed.append({"error": str(error)})

            # Store collection metadata
            results.processed.append(
                {
                    "goal_met": collection_result.goal_met,
                    "iterations": collection_result.iterations,
                    "by_source": dict(collection_result.progress.by_source)
                    if collection_result.progress.by_source
                    else {},
                    "by_type": dict(collection_result.progress.by_type)
                    if collection_result.progress.by_type
                    else {},
                    "by_category": dict(collection_result.progress.by_category)
                    if collection_result.progress.by_category
                    else {},
                }
            )

        except Exception as e:
            logger.error(f"Collection pipeline failed: {e}")
            results.failed.append({"error": str(e)})

        return results

    async def _run_news_collection(
        self,
        on_progress: Optional[Callable],
        collection_config: Dict[str, Any],
        **kwargs,
    ) -> PipelineResult:
        """Run ad-hoc news collection pipeline."""
        results = PipelineResult([], [], [], 0.0)

        try:
            # 1. Setup Configuration
            if on_progress:
                on_progress(
                    PipelineProgress(
                        current=1,
                        total=4,
                        question_id=None,
                        stage="setup",
                        message="Configuring news collection",
                    )
                )

            # Load and filter sources
            requested_domains = collection_config.get("domains")
            article_sources = self._load_article_sources(domains=requested_domains)

            if not article_sources:
                raise ValueError("No article sources available for requested domains")

            # Initialize Runner using helper
            runner = self._create_news_runner(
                article_sources=article_sources,
                domains=requested_domains or [],
                question_types=collection_config.get("question_types"),
                max_articles_per_source=collection_config.get(
                    "max_articles_per_source", 3
                ),
                days_back=7,
            )

            # 2. Run Collection
            if on_progress:
                on_progress(
                    PipelineProgress(
                        current=2,
                        total=4,
                        question_id=None,
                        stage="collection",
                        message="Collecting articles and generating questions",
                    )
                )

            collection_result = await runner.collect(
                count=collection_config.get("count", 5),
                type_filter=collection_config.get("question_types"),
                category_filter=requested_domains,
            )

            if on_progress:
                on_progress(
                    PipelineProgress(
                        current=3,
                        total=4,
                        question_id=None,
                        stage="collection",
                        message=f"Generated {len(collection_result.questions)} questions",
                    )
                )

            # 3. Processing Results
            for q in collection_result.questions:
                results.processed.append(
                    {
                        "id": q.id,
                        "text": q.question_text,
                        "type": q.question_type.value
                        if hasattr(q.question_type, "value")
                        else str(q.question_type).lower().split(".")[-1],
                        "domain": q.domain.value
                        if hasattr(q.domain, "value")
                        else str(q.domain).lower().split(".")[-1],
                        "source": q.source,
                        "resolution_date": q.resolution_date.isoformat()
                        if q.resolution_date
                        else None,
                        "resolution_criteria": q.resolution_criteria,
                        "ground_truth": q.ground_truth,
                        "resolution_reasoning": q.resolution_reasoning,
                        "difficulty": q.difficulty,
                        "related_event_ids": q.related_event_ids,
                        "estimated_start_time": q.estimated_start_time.isoformat()
                        if q.estimated_start_time
                        else None,
                        "metadata": q.metadata,
                    }
                )

            if collection_result.error_message:
                results.failed.append({"error": collection_result.error_message})

            # 4. Indexing
            if on_progress:
                on_progress(
                    PipelineProgress(
                        current=4,
                        total=4,
                        question_id=None,
                        stage="indexing",
                        message="Indexing collected articles",
                    )
                )
            await self._auto_index_articles()

        except Exception as e:
            logger.error(f"News collection failed: {e}")
            results.failed.append({"error": str(e)})

        return results

    async def _run_evidence(
        self,
        question_ids: List[str],
        on_progress: Optional[Callable],
        min_evidence_articles: Optional[int] = None,
        evidence_window_days: Optional[int] = None,
        force_reprocess: bool = False,
        skip_indexing: bool = False,
        min_graph_depth: int = SATISFACTION_DEFAULTS.min_graph_depth,
        **kwargs,
    ) -> PipelineResult:
        """Run basic evidence pipeline."""
        from src.pipelines.evidence import EvidencePipeline

        # Load defaults from source of truth
        default_config = EvidencePipelineConfig()

        if min_evidence_articles is None:
            min_evidence_articles = default_config.min_evidence_articles

        if evidence_window_days is None:
            evidence_window_days = default_config.evidence_window_days

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

        # Simple parallel execution
        semaphore = asyncio.Semaphore(PIPELINE_QUESTION_CONCURRENCY_LIMIT)

        async def process_question(i, qid):
            async with semaphore:
                try:
                    # Send progress update
                    if on_progress:
                        on_progress(
                            PipelineProgress(
                                current=i + 1,
                                total=len(question_ids),
                                question_id=qid,
                                stage="evidence",
                                message=f"Processing question {qid}",
                            )
                        )

                    # Check if already has evidence (unless force reprocess)
                    question = self.db.get(Question, qid)
                    if not question:
                        results.failed.append({"id": qid, "error": "Question not found"})
                        return

                    if not force_reprocess:
                        skip_reason = self._check_sufficient_evidence(question)
                        if skip_reason:
                            results.skipped.append({"id": qid, "reason": skip_reason})
                            return

                    # Run pipeline on single question
                    logger.info(f"Running evidence pipeline on question: {qid}")
                    pipeline_results = await pipeline.run([question])

                    # Check if pipeline succeeded (no FAILED stages and at least one result)
                    has_failure = any(
                        r.status == PipelineStageStatus.FAILED for r in pipeline_results
                    )

                    if pipeline_results and not has_failure:
                        # Count generated artifacts
                        articles = self.db.get_many(
                            Article, filters={"collected_for_question_id": qid}
                        )
                        hypotheses_count = self.db.count(
                            CausalHypothesis,
                            filters={"discovered_by_question_ids__like": f'%"{qid}"%'},
                        )

                        results.processed.append(
                            {
                                "id": qid,
                                "articles": len(articles),
                                "hypotheses": hypotheses_count,
                            }
                        )
                        logger.info(
                            f"Successfully processed {qid}: {len(articles)} articles, {hypotheses_count} hypotheses"
                        )
                    else:
                        error_msg = self._pipeline_error_message(pipeline_results)
                        results.failed.append({"id": qid, "error": error_msg})
                        logger.error(f"Failed to process {qid}: {error_msg}")

                except Exception as e:
                    logger.error(f"Error processing question {qid}: {e}")
                    results.failed.append({"id": qid, "error": str(e)})

        tasks = [process_question(i, qid) for i, qid in enumerate(question_ids)]
        await asyncio.gather(*tasks)

        if not skip_indexing:
            await self._auto_index_articles()

        return results

    async def _run_adaptive_evidence(
        self,
        question_ids: List[str],
        on_progress: Optional[Callable],
        agent_max_steps: int = 30,
        min_graph_depth: int = SATISFACTION_DEFAULTS.min_graph_depth,
        skip_indexing: bool = False,
        force_reprocess: bool = False,
        **kwargs,
    ) -> PipelineResult:
        """Run adaptive multi-agent evidence pipeline."""
        from src.pipelines.evidence.pipeline import EvidencePipeline

        evidence_config = EvidencePipelineConfig()
        database_config = DatabaseConfig(db_path=self.db_path)

        pipeline = EvidencePipeline(
            evidence_config=evidence_config,
            database_config=database_config,
            enable_persistence=True,
            min_quality_score=kwargs.get("min_quality_score"),
            agent_max_steps=agent_max_steps,
            min_graph_depth=min_graph_depth,
        )

        results = PipelineResult([], [], [], 0.0)
        semaphore = asyncio.Semaphore(PIPELINE_QUESTION_CONCURRENCY_LIMIT)

        async def process_question(i, qid):
            async with semaphore:
                try:
                    if on_progress:
                        on_progress(
                            PipelineProgress(
                                current=i + 1,
                                total=len(question_ids),
                                question_id=qid,
                                stage="adaptive_evidence",
                                message=f"Processing question {qid}",
                            )
                        )

                    question = self.db.get(Question, qid)
                    if not question:
                        results.failed.append({"id": qid, "error": "Question not found"})
                        return

                    if not force_reprocess:
                        skip_reason = self._check_sufficient_evidence(question)
                        if skip_reason:
                            results.skipped.append({"id": qid, "reason": skip_reason})
                            return

                    logger.info(f"Running adaptive evidence pipeline on question: {qid}")
                    pipeline_results = await pipeline.run([question])

                    has_failure = any(
                        r.status == PipelineStageStatus.FAILED for r in pipeline_results
                    )

                    if pipeline_results and not has_failure:
                        articles = self.db.get_many(
                            Article, filters={"collected_for_question_id": qid}
                        )
                        hypotheses_count = self.db.count(
                            CausalHypothesis,
                            filters={"discovered_by_question_ids__like": f'%"{qid}"%'},
                        )

                        results.processed.append(
                            {
                                "id": qid,
                                "articles": len(articles),
                                "hypotheses": hypotheses_count,
                            }
                        )
                        logger.info(
                            f"Successfully processed {qid}: {len(articles)} articles, {hypotheses_count} hypotheses"
                        )
                    else:
                        error_msg = self._pipeline_error_message(pipeline_results)
                        results.failed.append({"id": qid, "error": error_msg})
                        logger.error(f"Failed to process {qid}: {error_msg}")

                except Exception as e:
                    logger.error(f"Error processing question {qid}: {e}")
                    results.failed.append({"id": qid, "error": str(e)})

        tasks = [process_question(i, qid) for i, qid in enumerate(question_ids)]
        await asyncio.gather(*tasks)

        if not skip_indexing:
            await self._auto_index_articles()

        return results

    async def _run_forecast(
        self,
        question_ids: List[str],
        on_progress: Optional[Callable],
        model: Optional[str] = None,
        slot: str = "mid",
        mode: str = "container",
        enable_causal_tools: bool = False,
        min_context_items: int = 3,
        **kwargs,
    ) -> PipelineResult:
        """Run forecasting on questions."""
        from src.agents.forecast_agent import ForecastAgent
        from src.core.llm import get_knowledge_cutoff_date
        from src.domain.models.question_helpers import (
            ForecastSlot,
            get_forecast_date_for_slot,
        )
        from src.pipelines.prompts.forecast import get_forecast_instructions

        results = PipelineResult([], [], [], 0.0)

        # Override config model if specified
        config = self.config
        if model:
            config = deepcopy(self.config)
            config.llm.model = model

        for i, qid in enumerate(question_ids):
            try:
                if on_progress:
                    on_progress(
                        PipelineProgress(
                            current=i + 1,
                            total=len(question_ids),
                            question_id=qid,
                            stage="forecast",
                            message=f"Forecasting on question {qid}",
                        )
                    )

                question = self.db.get(Question, qid)
                if not question:
                    results.failed.append({"id": qid, "error": "Question not found"})
                    continue

                logger.info(f"Running forecast on question: {qid}")

                # Determine simulated date via slot-based approach
                try:
                    forecast_slot = ForecastSlot(slot)
                except ValueError:
                    forecast_slot = ForecastSlot.MID

                forecast_setup = get_forecast_date_for_slot(question, slot=forecast_slot)

                # Create forecast agent with correct parameters
                agent = ForecastAgent(
                    question=question,
                    simulated_date=forecast_setup["simulated_date"].isoformat(),
                    knowledge_cutoff=get_knowledge_cutoff_date(config.llm.model),
                    config=config,
                    db_path=self.db_path,  # Pass database path for per-request switching
                    mode=mode,
                    enable_causal_tools=enable_causal_tools,
                )
                prompt_instructions = get_forecast_instructions(
                    mode=mode,
                    enable_causal_tools=enable_causal_tools,
                )
                # Run agent to generate forecast
                result = agent.run(prompt_instructions)

                # The forecast should be submitted via the MCP tool and saved to DB
                # Check if forecast was created
                forecasts = self.db.get_many(Forecast, filters={"question_id": qid})

                if forecasts:
                    # Get the most recent forecast (using timestamp instead of created_at)
                    latest_forecast = sorted(
                        forecasts, key=lambda f: f.timestamp, reverse=True
                    )[0]
                    results.processed.append(
                        {
                            "id": qid,
                            "forecast_id": latest_forecast.id,
                            "prediction": latest_forecast.prediction,
                            "confidence": latest_forecast.confidence,
                        }
                    )
                    logger.info(
                        f"Successfully forecast {qid}: {latest_forecast.prediction} (confidence: {latest_forecast.confidence})"
                    )
                else:
                    results.failed.append(
                        {"id": qid, "error": "No forecast was created"}
                    )

            except Exception as e:
                logger.error(f"Error forecasting question {qid}: {e}")
                results.failed.append({"id": qid, "error": str(e)})

        return results

    async def _run_evaluation(
        self, question_ids: List[str], on_progress: Optional[Callable], **kwargs
    ) -> PipelineResult:
        """Run evaluation on existing forecasts."""
        from src.domain.evaluation import ForecastEvaluator

        evaluator = ForecastEvaluator()
        results = PipelineResult([], [], [], 0.0)

        for i, qid in enumerate(question_ids):
            try:
                if on_progress:
                    on_progress(
                        PipelineProgress(
                            current=i + 1,
                            total=len(question_ids),
                            question_id=qid,
                            stage="evaluation",
                            message=f"Evaluating forecasts for question {qid}",
                        )
                    )

                question = self.db.get(Question, qid)
                if not question:
                    results.failed.append({"id": qid, "error": "Question not found"})
                    continue

                # Get forecasts for this question
                forecasts = self.db.get_many(Forecast, filters={"question_id": qid})

                if not forecasts:
                    results.skipped.append({"id": qid, "reason": "No forecasts found"})
                    continue

                logger.info(
                    f"Evaluating {len(forecasts)} forecasts for question: {qid}"
                )

                evaluated_count = 0
                for forecast in forecasts:
                    evaluation = evaluator.evaluate(forecast, question)
                    if evaluation:
                        # Save evaluation metrics back to forecast
                        forecast.evaluation = evaluation.dict()
                        self.db.save(Forecast, forecast)
                        evaluated_count += 1

                results.processed.append(
                    {
                        "id": qid,
                        "forecasts_evaluated": evaluated_count,
                    }
                )

            except Exception as e:
                logger.error(f"Error evaluating question {qid}: {e}")
                results.failed.append({"id": qid, "error": str(e)})

        return results

    async def _run_benchmark(
        self, question_ids: List[str], on_progress: Optional[Callable], **kwargs
    ) -> PipelineResult:
        """Run benchmark (forecast + evaluate) on questions."""
        # First forecast
        forecast_result = await self._run_forecast(question_ids, on_progress, **kwargs)

        # Only evaluate successfully forecasted questions
        successful_ids = [r["id"] for r in forecast_result.processed]

        eval_result = await self._run_evaluation(successful_ids, on_progress, **kwargs)

        return PipelineResult(
            processed=eval_result.processed,
            failed=forecast_result.failed + eval_result.failed,
            skipped=forecast_result.skipped + eval_result.skipped,
            duration_seconds=0.0,
        )

    async def _run_auto_benchmark(
        self, question_ids: List[str], on_progress: Optional[Callable], **kwargs
    ) -> PipelineResult:
        """Run auto-benchmark across conditions, models, and questions."""
        from src.domain.evaluation.auto_benchmark import (
            AutoBenchmarkService,
            AutoBenchmarkProgress,
        )
        from src.domain.evaluation.conditions import get_conditions

        results = PipelineResult([], [], [], 0.0)

        try:
            service = AutoBenchmarkService(
                db_path=self.db_path,
                config=self.config,
                output_dir=kwargs.get("output_dir", "benchmarks"),
            )

            # Get questions
            questions = service.get_resolved_questions(
                question_ids=question_ids if question_ids else None,
                max_questions=kwargs.get("max_questions"),
                source=kwargs.get("source"),
                domain=kwargs.get("domain"),
            )

            if not questions:
                results.failed.append({"error": "No resolved questions found"})
                return results

            # Get models
            models = kwargs.get("models", [self.config.llm.model])

            # Get conditions
            condition_names = kwargs.get("conditions")
            conditions = get_conditions(condition_names)

            # Map progress
            def progress_adapter(p: AutoBenchmarkProgress):
                if on_progress:
                    on_progress(
                        PipelineProgress(
                            current=p.overall_current,
                            total=p.overall_total,
                            question_id=p.question_id,
                            stage=p.condition_name,
                            message=f"{p.model_name} | {p.question_id}",
                        )
                    )

            benchmark_result = service.run_auto_benchmark(
                questions=questions,
                models=models,
                conditions=conditions,
                slot=kwargs.get("slot", "mid"),
                on_progress=progress_adapter,
                resume=kwargs.get("resume", False),
            )

            results.processed.append(
                {
                    "run_id": benchmark_result.run_id,
                    "duration_seconds": benchmark_result.duration_seconds,
                    "comparative_summary": benchmark_result.comparative_summary,
                    "benchmark_result": benchmark_result,
                }
            )

        except Exception as e:
            logger.error(f"Auto-benchmark failed: {e}")
            results.failed.append({"error": str(e)})

        return results

    async def _run_reasoning_eval(
        self,
        on_progress: Optional[Callable],
        include_ids: Optional[str] = None,
        filter_knowledge_leakage: bool = True,
        exclude_annotation_rejected: bool = True,
        match_method: str = "hybrid",
        output_dir: str = "experiments/evaluation/canonical_final",
        **kwargs,
    ) -> PipelineResult:
        """Run reasoning-graph evaluation against hindsight graphs.

        Calls scripts/benchmark/evaluate_reasoning_graphs.py as a subprocess
        so its heavy dependencies (BM25, optional sentence-transformers) are
        isolated from the main server process.
        """
        import asyncio
        import sys
        from pathlib import Path

        results = PipelineResult(processed=[], failed=[], skipped=[], duration_seconds=0)

        if on_progress:
            on_progress(PipelineProgress(
                current=0, total=1, question_id=None,
                stage="reasoning_eval",
                message="Starting reasoning-graph evaluation…",
            ))

        script = Path(__file__).resolve().parents[2] / "scripts/benchmark/evaluate_reasoning_graphs.py"
        cmd = [sys.executable, str(script), "--db", str(self.db_path)]

        if include_ids:
            cmd += ["--include-ids", include_ids]
        if filter_knowledge_leakage:
            cmd += ["--filter-knowledge-leakage"]
        if exclude_annotation_rejected:
            cmd += ["--exclude-annotation-rejected"]

        cmd += ["--match-method", match_method, "--output-dir", output_dir]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await proc.communicate()
            output = stdout.decode(errors="replace") if stdout else ""

            if proc.returncode == 0:
                output_path = Path(output_dir) / "reasoning_graph_eval_filtered_latest.json"
                results.processed.append({
                    "output": str(output_path),
                    "returncode": 0,
                    "log": output[-2000:] if len(output) > 2000 else output,
                })
                if on_progress:
                    on_progress(PipelineProgress(
                        current=1, total=1, question_id=None,
                        stage="reasoning_eval",
                        message=f"Evaluation complete → {output_path.name}",
                    ))
            else:
                logger.error(f"Reasoning eval failed (rc={proc.returncode}): {output[-500:]}")
                results.failed.append({"error": output[-500:], "returncode": proc.returncode})

        except Exception as e:
            logger.error(f"Reasoning eval subprocess error: {e}")
            results.failed.append({"error": str(e)})

        return results

    async def _run_graph_builder(
        self,
        question_ids: List[str],
        on_progress: Optional[Callable],
        force: bool = False,
        min_graph_depth: int = SATISFACTION_DEFAULTS.min_graph_depth,
        min_events: int = SATISFACTION_DEFAULTS.min_graph_events,
        **kwargs,
    ) -> PipelineResult:
        """Build causal graphs for questions that already have a causal explanation."""
        from src.pipelines.graph_builder.pipeline import GraphBuilderPipeline

        config = self.config
        pipeline = GraphBuilderPipeline(
            db_path=self.db_path,
            model_id=config.llm.model,
            min_graph_depth=min_graph_depth,
            min_events=min_events,
        )

        results = PipelineResult([], [], [], 0.0)
        semaphore = asyncio.Semaphore(PIPELINE_QUESTION_CONCURRENCY_LIMIT)

        async def process_question(i, qid):
            async with semaphore:
                if on_progress:
                    on_progress(
                        PipelineProgress(
                            current=i + 1,
                            total=len(question_ids),
                            question_id=qid,
                            stage="graph_builder",
                            message=f"Building graph for {qid}",
                        )
                    )

                question = self.db.get(Question, qid)
                if not question:
                    results.failed.append({"id": qid, "error": "Question not found"})
                    return

                if not question.causal_explanation:
                    results.skipped.append({"id": qid, "reason": "No causal explanation — run evidence pipeline first"})
                    return

                if not force and question.graph_built:
                    results.skipped.append({"id": qid, "reason": "Graph already built (use force to rebuild)"})
                    return

                try:
                    success = await asyncio.to_thread(pipeline._process_single_question, question)
                    if success:
                        results.processed.append({"id": qid})
                    else:
                        results.failed.append({"id": qid, "error": "Graph building failed"})
                except Exception as e:
                    logger.error(f"Graph builder error for {qid}: {e}")
                    results.failed.append({"id": qid, "error": str(e)})

        tasks = [process_question(i, qid) for i, qid in enumerate(question_ids)]
        await asyncio.gather(*tasks)

        return results

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
        from src.services.question_service import QuestionService

        service = QuestionService(self.db)
        results = {"cleared": [], "failed": []}

        for qid in question_ids:
            try:
                service.clear_evidence(qid, cascade=cascade)
                results["cleared"].append(qid)
            except Exception as e:
                logger.error(f"Failed to clear evidence for {qid}: {e}")
                results["failed"].append({"id": qid, "error": str(e)})

        return results
