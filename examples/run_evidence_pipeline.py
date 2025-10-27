"""Example script for running the Evidence Pipeline.

This script demonstrates how to run the Evidence Pipeline to build
causal explanations with hindsight.

Prerequisites:
1. Set up config/local.yaml with LLM API keys
2. Have resolved questions in the database (from Question Pipeline)
3. Ensure questions have resolution_date and ground_truth set

Usage:
    python examples/run_evidence_pipeline.py
"""

import asyncio
from src.pipelines.evidence import EvidencePipeline
from src.config.pipeline import EvidencePipelineConfig
from src.config import DatabaseConfig, get_config
from src.utils.logging import logger


async def main():
    """Run the Evidence Pipeline."""

    logger.info("=" * 80)
    logger.info("Evidence Pipeline - Causal Analysis with Hindsight")
    logger.info("=" * 80)

    # Load configuration
    app_config = get_config()

    # Configure Evidence Pipeline
    evidence_config = EvidencePipelineConfig(
        # Evidence collection settings
        evidence_window_days=30,              # Search 30 days before resolution
        min_evidence_articles=5,              # Collect at least 5 articles per question
        include_expert_analysis=True,         # Prioritize expert analysis

        # Causal reasoning thresholds
        causal_confidence_threshold=0.6,      # Minimum confidence: 0.6
        causal_strength_threshold=0.3,        # Minimum strength: 0.3
        require_evidence=True,                # Must cite evidence articles
        max_causal_depth=3,                   # Max causal chain length

        # Graph building settings
        allow_causal_cycles=False,            # Prevent circular causality
        validate_temporal_ordering=True,      # Ensure causes precede effects
        max_links_per_event=10,              # Max links per event

        # Question filtering
        min_resolution_age_days=1,           # Min 1 day since resolution
        max_resolution_age_days=365,         # Max 365 days since resolution
        max_questions=2,                      # Process only 2 questions (for testing)
        skip_already_processed=True,          # Skip questions already processed (set False to force re-process)

        # Batch processing
        question_batch_size=10,
        reasoning_batch_size=20,
    )

    # Database configuration
    db_config = DatabaseConfig(
        db_path=app_config.database.db_path,
        batch_size=app_config.database.batch_size,
    )

    logger.info("\nConfiguration:")
    logger.info(f"  - Database: {db_config.db_path}")
    logger.info(f"  - Evidence window: {evidence_config.evidence_window_days} days before resolution")
    logger.info(f"  - Min evidence articles: {evidence_config.min_evidence_articles}")
    logger.info(f"  - Confidence threshold: {evidence_config.causal_confidence_threshold}")
    logger.info(f"  - Strength threshold: {evidence_config.causal_strength_threshold}")
    logger.info(f"  - Max questions to process: {evidence_config.max_questions or 'unlimited'}")
    logger.info(f"  - Skip already processed: {evidence_config.skip_already_processed}")

    # Create pipeline
    logger.info("\nInitializing Evidence Pipeline...")
    pipeline = EvidencePipeline(
        evidence_config=evidence_config,
        database_config=db_config,
        enable_persistence=True  # Save results to database
    )

    # Run pipeline (it will automatically load and limit questions based on config)
    logger.info("\nRunning Evidence Pipeline...")
    logger.info("This will:")
    logger.info("  1. Load resolved questions from database (limited by config)")
    logger.info("  2. Collect evidence articles (before resolution)")
    logger.info("  3. Identify causal relationships")
    logger.info("  4. Build causal graph with validated links")
    logger.info("")

    try:
        results = await pipeline.run()  # Let pipeline load questions from DB

        # Display results
        logger.info("\n" + "=" * 80)
        logger.info("PIPELINE COMPLETED SUCCESSFULLY")
        logger.info("=" * 80)

        summary = pipeline.get_summary()

        logger.info("\nResults Summary:")
        logger.info(f"  - Resolved questions processed: {summary['resolved_questions']}")
        logger.info(f"  - Evidence articles collected: {summary['evidence_articles']}")
        logger.info(f"  - Causal hypotheses generated: {summary['causal_hypotheses']}")
        logger.info(f"  - Events enhanced: {summary['enhanced_events']}")
        logger.info(f"  - Stages completed: {summary['stages_completed']}/{len(pipeline.stages)}")

        if summary['stages_failed'] > 0:
            logger.warning(f"  - Stages failed: {summary['stages_failed']}")

        # Display stage metrics
        logger.info("\nStage Metrics:")
        for result in results:
            logger.info(f"  - {result.stage_name}:")
            logger.info(f"      Status: {result.status.value}")
            logger.info(f"      Processed: {result.items_processed}")
            logger.info(f"      Output: {result.items_output}")
            logger.info(f"      Duration: {result.duration_seconds():.2f}s")

        # Sample outputs
        if pipeline.causal_hypotheses:
            logger.info("\nSample Causal Hypotheses:")
            for i, hyp in enumerate(pipeline.causal_hypotheses[:3], 1):
                logger.info(f"  {i}. {hyp.source_event_id} -> {hyp.target_event_id}")
                logger.info(f"     Relation: {hyp.relation_type.value}")
                logger.info(f"     Strength: {hyp.strength:.2f}, Confidence: {hyp.confidence:.2f}")
                logger.info(f"     Evidence: {len(hyp.evidence_article_ids)} articles")

        if pipeline.enhanced_events:
            logger.info("\nSample Enhanced Events:")
            for i, event in enumerate(pipeline.enhanced_events[:3], 1):
                logger.info(f"  {i}. {event.title} ({event.id})")
                logger.info(f"     Causal links added: {len(event.causes)}")
                logger.info(f"     Caused by: {len(event.caused_by_ids)} events")

        logger.info("\n" + "=" * 80)
        logger.info("Evidence Pipeline completed successfully!")
        logger.info("Results have been persisted to the database.")
        logger.info("=" * 80)

    except Exception as e:
        logger.error("\n" + "=" * 80)
        logger.error("PIPELINE FAILED")
        logger.error("=" * 80)
        logger.error(f"Error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise


if __name__ == "__main__":
    asyncio.run(main())
