"""
CLI script to run the configurable Evidence Pipeline.

This script demonstrates how to run the Evidence Pipeline to build
causal explanations with hindsight.

Prerequisites:
1. Set up config/local.yaml with LLM API keys
2. Have resolved questions in the database (from Question Pipeline)
3. Ensure questions have resolution_date and ground_truth set

Usage:
    # Run with defaults (process 2 questions max, skip already processed)
    python examples/run_evidence_pipeline.py

    # Process all unprocessed questions
    python examples/run_evidence_pipeline.py --max-questions 0

    # Force re-process all questions (ignore existing hypotheses)
    python examples/run_evidence_pipeline.py --force-reprocess

    # Process questions from specific domain
    python examples/run_evidence_pipeline.py --domains tech --max-questions 5

    # Custom thresholds
    python examples/run_evidence_pipeline.py --confidence 0.7 --strength 0.4

Note:
    Articles are automatically indexed for hybrid search after pipeline completion.
    Use --skip-indexing to disable this behavior.
"""

import argparse
import asyncio
from src.pipelines.evidence import EvidencePipeline
from src.config.pipeline import EvidencePipelineConfig
from src.config import DatabaseConfig, get_config
from src.utils.logging import logger
from src.utils.search_indexing import auto_index_articles, should_auto_index
from src.utils.question_loader import load_specific_question


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run the WorldReasoner Evidence Pipeline for causal analysis."
    )

    # Database configuration
    parser.add_argument('--db', type=str, default='worldreasoner.db', help='Path to database file (default: worldreasoner.db)')

    # Question filtering
    parser.add_argument('--question-id', type=str, default='', help='Process specific question by ID (overrides other filters)')
    parser.add_argument('--max-questions', type=int, default=10, help='Maximum questions to process (0 = unlimited, default: 2)')
    parser.add_argument('--domains', type=str, default='', help='Comma-separated list of domains (e.g., tech,finance,politics)')
    parser.add_argument('--force-reprocess', action='store_true', help='Re-process questions even if they already have hypotheses')

    # Evidence collection settings
    parser.add_argument('--evidence-window', type=int, default=365, help='Days before resolution to collect evidence')
    parser.add_argument('--min-resolution-age', type=int, default=0, help='Minimum days since resolution required to process (default: 0)')
    parser.add_argument('--min-articles', type=int, default=5, help='Minimum evidence articles per question (default: 5)')

    # Causal reasoning thresholds
    parser.add_argument('--confidence', type=float, default=0.6, help='Minimum confidence threshold (0.0-1.0, default: 0.6)')
    parser.add_argument('--strength', type=float, default=0.3, help='Minimum causal strength threshold (0.0-1.0, default: 0.3)')
    
    # New argument for quality score
    parser.add_argument('--min-quality-score', type=float, default=None, help='Minimum quality score to process a question (0.0-1.0)')

    # Processing settings
    parser.add_argument('--question-batch-size', type=int, default=10, help='Batch size for evidence collection (default: 10)')
    parser.add_argument('--reasoning-batch-size', type=int, default=20, help='Batch size for causal reasoning (default: 20)')

    # Output control
    parser.add_argument('--verbose', action='store_true', help='Show detailed output with sample results')
    parser.add_argument('--skip-indexing', action='store_true', help='Skip automatic search indexing after pipeline completion')

    return parser.parse_args()


async def run_pipeline(args):
    """Run the Evidence Pipeline with provided arguments.

    Args:
        args: Parsed command line arguments
    """
    # Load configuration
    app_config = get_config()

    # Configure Evidence Pipeline
    max_questions = args.max_questions if args.max_questions > 0 else None
    domains = [d.strip() for d in args.domains.split(',') if d.strip()] if args.domains else []
    question_id = args.question_id.strip() if args.question_id else None

    evidence_config = EvidencePipelineConfig(
        # Evidence collection settings
        evidence_window_days=args.evidence_window,
        min_evidence_articles=args.min_articles,
        include_expert_analysis=True,

        # Causal reasoning thresholds
        causal_confidence_threshold=args.confidence,
        causal_strength_threshold=args.strength,
        require_evidence=True,
        max_causal_depth=3,

        # Graph building settings
        allow_causal_cycles=False,
        validate_temporal_ordering=True,
        max_links_per_event=10,

        # Question filtering
        max_resolution_age_days=365,
        # Allow override from CLI
        min_resolution_age_days=args.min_resolution_age,
        max_questions=max_questions,
        skip_already_processed=not args.force_reprocess,
        domains=domains,

        # Batch processing
        question_batch_size=args.question_batch_size,
        reasoning_batch_size=args.reasoning_batch_size,
    )

    # Database configuration
    db_config = DatabaseConfig(
        db_path=args.db,
        batch_size=app_config.database.batch_size,
    )

    # Log configuration
    logger.info("=" * 80)
    logger.info("Evidence Pipeline - Causal Analysis with Hindsight")
    logger.info("=" * 80)
    logger.info(f"\nDatabase: {db_config.db_path}")
    if question_id:
        logger.info(f"Specific question: {question_id}")
    logger.info(f"Evidence window: {evidence_config.evidence_window_days} days before resolution")
    logger.info(f"Min evidence articles: {evidence_config.min_evidence_articles}")
    logger.info(f"Confidence threshold: {evidence_config.causal_confidence_threshold}")
    logger.info(f"Strength threshold: {evidence_config.causal_strength_threshold}")
    logger.info(f"Max questions: {evidence_config.max_questions or 'unlimited'}")
    logger.info(f"Skip already processed: {evidence_config.skip_already_processed}")
    if domains:
        logger.info(f"Domain filter: {', '.join(domains)}")
    if args.min_quality_score is not None:
        logger.info(f"Minimum quality score: {args.min_quality_score}")
    logger.info("")

    # Handle specific question ID if provided
    resolved_questions = load_specific_question(args.db, question_id) if question_id else None
    if question_id and resolved_questions is None:
        return  # Error already logged by helper

    # Create pipeline
    pipeline = EvidencePipeline(
        evidence_config=evidence_config,
        database_config=db_config,
        enable_persistence=True,
        min_quality_score=args.min_quality_score,
    )

    # Run pipeline
    try:
        results = await pipeline.run(resolved_questions=resolved_questions)

        # Display results
        summary = pipeline.get_summary()

        logger.info("=" * 80)
        logger.info("PIPELINE COMPLETED")
        logger.info("=" * 80)
        # Display DB-level question stats (snapshot taken before this run)
        db_total = summary.get('db_total_questions')
        db_resolved = summary.get('db_resolved_questions')
        db_unprocessed = summary.get('db_unprocessed_questions')
        if isinstance(db_total, int) and isinstance(db_resolved, int) and isinstance(db_unprocessed, int):
            logger.info(
                f"DB snapshot (pre-run): total={db_total}, resolved={db_resolved}, unprocessed={db_unprocessed}"
            )

        # Note: 'resolved_questions' is how many questions were attempted in THIS run
        processed_this_run = summary['resolved_questions']
        logger.info(f"Questions processed (this run, after filters/limits): {processed_this_run}")
        # Provide an approximate remaining count for convenience
        if isinstance(db_unprocessed, int):
            remaining_est = max(db_unprocessed - processed_this_run, 0)
            logger.info(f"Approx. remaining unprocessed after this run: {remaining_est}")
            logger.info("Tip: use --max-questions 0 to process all matching questions in one run.")

        logger.info(f"Evidence articles: {summary['evidence_articles']}")
        logger.info(f"Causal hypotheses: {summary['causal_hypotheses']}")
        logger.info(f"Stage executions: {summary['stages_completed']} completed, {summary['stages_failed']} failed")

        # Show stage details
        logger.info("Stage Results:")
        for i, result in enumerate(results, 1):
            status_symbol = "✓" if result.status.value == "completed" else "✗"
            logger.info(
                f"  {i}. {result.stage_name}: {result.items_processed} processed, "
                f"{result.items_output} output ({result.duration_seconds():.1f}s) {status_symbol}"
            )
            if result.error_message:
                logger.error(f"     Error: {result.error_message}")

        # Verbose output with samples
        if args.verbose:
            if pipeline.causal_hypotheses:
                logger.info("\nSample Causal Hypotheses:")
                for i, hyp in enumerate(pipeline.causal_hypotheses[:3], 1):
                    logger.info(f"  {i}. {hyp.source_event_id} -> {hyp.target_event_id}")
                    logger.info(f"     {hyp.relation_type.value} (strength: {hyp.strength:.2f}, confidence: {hyp.confidence:.2f})")
                    logger.info(f"     Evidence: {len(hyp.evidence_article_ids)} articles")
                    logger.info(f"     Discovered by: {len(hyp.discovered_by_question_ids)} question(s)")

        # Auto-index articles for search if not skipped
        if should_auto_index(args.skip_indexing):
            logger.info("")
            logger.info("Indexing articles for hybrid search...")
            index_stats = await auto_index_articles(db_path=args.db)
            if index_stats['status'] == 'success':
                logger.info(f"✓ Indexed {index_stats['newly_indexed']} new articles")
                logger.info(f"  Total indexed: {index_stats['final_indexed']}")
            elif index_stats['status'] == 'up_to_date':
                logger.info("✓ Search index is up to date")
            elif index_stats['status'] == 'no_articles':
                logger.warning("⚠ No articles to index")
            else:
                logger.error(f"✗ Indexing failed: {index_stats.get('error', 'Unknown error')}")

        logger.info("=" * 80)

    except Exception as e:
        logger.error("=" * 80)
        logger.error("PIPELINE FAILED")
        logger.error("=" * 80)
        logger.error(f"Error: {e}")

        if args.verbose:
            import traceback
            logger.error(traceback.format_exc())

        raise


def main():
    """Main entry point."""
    args = parse_args()
    asyncio.run(run_pipeline(args))


if __name__ == "__main__":
    main()
