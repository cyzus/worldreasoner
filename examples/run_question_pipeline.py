"""
CLI script to run the configurable QuestionPipeline.

Usage:
    python run_question_pipeline.py --sources config/sources.yaml --db output.db --start-date YYYY-MM-DD --end-date YYYY-MM-DD --domains tech,finance --max-questions 10 --article-batch-size 50 --event-batch-size 20
"""
import argparse
from datetime import datetime, timedelta, timezone, date
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
    parser.add_argument('--max-questions', type=int, default=10, help='Maximum questions to generate')
    parser.add_argument('--article-batch-size', type=int, default=20, help='Batch size for event identification (articles)')
    parser.add_argument('--event-batch-size', type=int, default=20, help='Batch size for question generation (events)')
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
    start_date = args.start_date or (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d") # Default to 7 days ago
    end_date = args.end_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    domains = [d.strip() for d in args.domains.split(',') if d.strip()] if args.domains else []
    sources = load_sources(args.sources, domains)
    if not sources:
        print("No sources found for the specified domains.")
        return
    question_config = QuestionPipelineConfig(
        max_questions=args.max_questions,
        domains=domains if domains else ["finance", "politics", "tech", "health", "climate"],
        start_date=datetime.strptime(start_date, "%Y-%m-%d").date(),
        end_date=datetime.strptime(end_date, "%Y-%m-%d").date(),
        article_batch_size=args.article_batch_size,
        event_batch_size=args.event_batch_size,
    )
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
