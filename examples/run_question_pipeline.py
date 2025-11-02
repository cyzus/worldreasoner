"""
CLI script to run the configurable QuestionPipeline.

Usage:
    python run_question_pipeline.py --sources config/sources.yaml --db output.db --start-date YYYY-MM-DD --end-date YYYY-MM-DD --domains tech,finance --max-questions 10 --article-batch-size 50 --event-batch-size 20
"""
import argparse
from datetime import datetime
import yaml
import asyncio
from src.pipelines.question.pipeline import QuestionPipeline
from src.config.pipeline import QuestionPipelineConfig
from src.config.database import DatabaseConfig
from src.pipelines.stages.article_collection import ArticleSource


def parse_args():
    parser = argparse.ArgumentParser(description="Run the WorldReasoner question pipeline.")
    parser.add_argument('--sources', type=str, default='config/sources.yaml', help='Path to sources.yaml config file')
    parser.add_argument('--db', type=str, default='worldreasoner.db', help='Path to output database file')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--domains', type=str, default='', help='Comma-separated list of domains (optional)')
    # If not specified, defer to config defaults by using None here
    parser.add_argument('--max-questions', type=int, default=None, help='Maximum questions to generate (defaults to config)')
    parser.add_argument('--article-batch-size', type=int, default=None, help='Batch size for event identification (articles) (defaults to config)')
    parser.add_argument('--event-batch-size', type=int, default=None, help='Batch size for question generation (events) (defaults to config)')
    return parser.parse_args()


def load_sources(sources_path, domains):
    with open(sources_path, 'r', encoding='utf-8') as f:
        config_data = yaml.safe_load(f)
    sources = []
    for source_data in config_data.get('sources', []):
        if domains and source_data.get('domain') not in domains:
            continue
        sources.append(ArticleSource(
            name=source_data['name'],
            url=source_data['url'],
            scraper_type=source_data['scraper_type'],
            rate_limit_per_second=source_data.get('rate_limit_per_second', 1.0)
        ))
    return sources


async def run_pipeline(args):
    # Parse dates only if provided; otherwise let config defaults apply
    start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date() if args.start_date else None
    end_date = datetime.strptime(args.end_date, "%Y-%m-%d").date() if args.end_date else None
    domains = [d.strip() for d in args.domains.split(',') if d.strip()] if args.domains else []
    sources = load_sources(args.sources, domains)
    if not sources:
        print("No sources found for the specified domains.")
        return
    # Build config kwargs: only pass values explicitly provided; otherwise rely on model defaults
    config_kwargs = {}
    if args.max_questions is not None:
        config_kwargs["max_questions"] = args.max_questions
    if start_date is not None:
        config_kwargs["start_date"] = start_date
    if end_date is not None:
        config_kwargs["end_date"] = end_date
    if args.article_batch_size is not None:
        config_kwargs["article_batch_size"] = args.article_batch_size
    if args.event_batch_size is not None:
        config_kwargs["event_batch_size"] = args.event_batch_size
    if domains:
        config_kwargs["domains"] = domains

    question_config = QuestionPipelineConfig(**config_kwargs)
    db_config = DatabaseConfig(db_path=args.db)
    pipeline = QuestionPipeline(
        question_config=question_config,
        database_config=db_config,
        article_sources=sources,
        enable_persistence=True
    )
    results = await pipeline.run()
    print("Pipeline completed.")
    for i, result in enumerate(results):
        print(f"Stage {i+1}: {result.stage_name} - Status: {result.status.value}")
        if result.error_message:
            print(f"  Error: {result.error_message}")
        print(f"  Outputs: {len(result.outputs)}")


def main():
    args = parse_args()
    asyncio.run(run_pipeline(args))


if __name__ == "__main__":
    main()
