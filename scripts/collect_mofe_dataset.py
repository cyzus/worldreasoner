"""Collect binary questions for the MoFE dataset.

Two-phase collection:
  Phase 1: Polymarket — fetch ALL binary questions (no domain filter), filter noise
  Phase 2: News pipeline — generate binary questions to fill domain gaps

Usage:
    python scripts/collect_mofe_dataset.py --db mofe_dataset.db --phase 1
    python scripts/collect_mofe_dataset.py --db mofe_dataset.db --phase 2
    python scripts/collect_mofe_dataset.py --db mofe_dataset.db --phase all
"""

import asyncio
import argparse
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config.collection_goal import CollectionGoal
from src.config.pipeline import QuestionPipelineConfig
from src.core.database import GenericDatabase
from src.domain.models import Question, Article, Event, CausalHypothesis
from src.pipelines.collection.runner_polymarket import PolymarketRunner
from src.utils.logging import logger

NOISE_PATTERNS = [
    re.compile(r"Up or Down.*\d{1,2}:\d{2}\s*(AM|PM)", re.IGNORECASE),
    re.compile(r"Up or Down.*\d{1,2}:\d{2}\s*(AM|PM).*\d{1,2}:\d{2}\s*(AM|PM)", re.IGNORECASE),
]


def is_noise_question(text: str) -> bool:
    return any(p.search(text) for p in NOISE_PATTERNS)


def print_distribution(questions, title=""):
    types = Counter()
    domains = Counter()
    sources = Counter()
    for q in questions:
        qt = q.question_type.value if hasattr(q.question_type, "value") else str(q.question_type)
        d = q.domain.value if hasattr(q.domain, "value") else str(q.domain)
        types[qt] += 1
        domains[d] += 1
        sources[q.source] += 1

    print(f"\n{'=' * 60}")
    print(f"  {title} ({len(questions)} questions)")
    print(f"{'=' * 60}")
    print(f"  Types: {dict(types)}")
    print(f"  Domains: {dict(domains.most_common())}")
    print(f"  Sources: {dict(sources)}")


async def phase1_polymarket(db_path: str) -> list:
    """Phase 1: Collect binary questions from Polymarket without domain restriction."""
    print("\n" + "=" * 60)
    print("  PHASE 1: Polymarket Binary Collection")
    print("=" * 60)

    runner = PolymarketRunner(min_volume_usd=0.0, require_ground_truth=True)

    result = await runner.collect(
        count=2000,
        type_filter=["binary"],
        category_filter=None,
    )

    all_qs = result.questions
    print(f"\n  Raw Polymarket binary: {len(all_qs)}")

    noise_count = 0
    clean_qs = []
    for q in all_qs:
        if is_noise_question(q.question_text):
            noise_count += 1
        else:
            clean_qs.append(q)

    print(f"  Removed noise (5-min crypto slots): {noise_count}")
    print(f"  Clean binary questions: {len(clean_qs)}")

    print_distribution(clean_qs, "Phase 1 Result")

    print(f"\n  Sample questions:")
    for q in clean_qs[:20]:
        d = q.domain.value if hasattr(q.domain, "value") else str(q.domain)
        gt = str(q.ground_truth)[:8] if q.ground_truth else "N/A"
        print(f"    [{d:10s}] gt={gt:8s} | {q.question_text[:60]}")

    return clean_qs


async def phase2_news(db_path: str, existing_domains: Counter) -> list:
    """Phase 2: Collect binary questions from news to fill domain gaps."""
    print("\n" + "=" * 60)
    print("  PHASE 2: News Pipeline Binary Collection")
    print("=" * 60)

    from src.pipelines.collection import ArticleCollectionConfig, ArticleSource, NewsBasedRunner

    import yaml
    with open("config/sources.yaml") as f:
        config_data = yaml.safe_load(f)

    sources = []
    for src_data in config_data.get("sources", []):
        try:
            sources.append(ArticleSource(**src_data))
        except Exception as e:
            logger.warning(f"Skipping invalid source: {e}")

    domain_targets = {
        "health": 12, "climate": 12, "science": 12,
        "finance": 10, "business": 8, "culture": 6,
        "sports": 5, "tech": 5, "general": 3, "politics": 0,
    }

    needed_per_domain = {}
    for d, target in domain_targets.items():
        current = existing_domains.get(d, 0)
        gap = max(0, target - current)
        if gap > 0:
            needed_per_domain[d] = gap

    print(f"  Domain gaps to fill: {needed_per_domain}")
    total_needed = sum(needed_per_domain.values())
    print(f"  Total questions needed from news: {total_needed}")

    if total_needed == 0:
        print("  All domains sufficiently covered!")
        return []

    matching_sources = [s for s in sources if s.domain in needed_per_domain]
    if not matching_sources:
        matching_sources = sources

    print(f"  Using {len(matching_sources)} article sources")

    article_config = ArticleCollectionConfig(
        sources=matching_sources,
        start_date=datetime.now(timezone.utc) - timedelta(days=365),
        end_date=datetime.now(timezone.utc),
        max_articles_per_source=15,
        domains=list(needed_per_domain.keys()),
    )

    question_config = QuestionPipelineConfig(
        max_questions=total_needed + 30,
        domains=list(needed_per_domain.keys()),
        question_types=["binary"],
        require_ground_truth=True,
        article_batch_size=5,
    )

    news_runner = NewsBasedRunner(
        article_config=article_config,
        question_config=question_config,
        db_path=db_path,
    )

    result = await news_runner.collect(
        count=total_needed + 20,
        type_filter=["binary"],
        category_filter=needed_per_domain,
    )

    print(f"\n  News pipeline collected: {len(result.questions)} questions")
    if result.questions:
        print_distribution(result.questions, "Phase 2 Result")

    return result.questions


SEARCH_TOPICS = {
    "health": [
        "FDA drug approval 2025",
        "WHO pandemic declaration 2025",
        "vaccine approval breakthrough 2025",
        "major clinical trial results 2025 2026",
        "Medicare Medicaid policy change 2025",
        "obesity drug GLP-1 approval 2025 2026",
        "bird flu H5N1 outbreak US 2025",
    ],
    "climate": [
        "COP climate summit agreement 2025",
        "extreme weather record 2025 2026",
        "renewable energy milestone 2025",
        "carbon emissions record 2025",
        "climate policy EU US 2025",
        "natural disaster earthquake hurricane 2025 2026",
        "deforestation Amazon rate 2025",
    ],
    "science": [
        "space mission launch success 2025 2026",
        "AI breakthrough benchmark record 2025",
        "physics discovery Nobel Prize 2025",
        "gene therapy CRISPR approval 2025",
        "quantum computing milestone 2025",
        "Mars mission rover discovery 2025",
        "fusion energy breakthrough 2025 2026",
    ],
    "finance": [
        "stock market crash correction 2025",
        "Federal Reserve interest rate decision 2025 2026",
        "major IPO 2025",
        "cryptocurrency regulation SEC 2025",
        "bank failure 2025",
        "inflation rate CPI 2025 2026",
        "major merger acquisition 2025",
    ],
    "business": [
        "major tech company layoffs 2025",
        "CEO resignation fired 2025 2026",
        "antitrust lawsuit ruling 2025",
        "startup unicorn valuation 2025",
        "major product launch recall 2025",
        "trade war tariff 2025 2026",
    ],
    "culture": [
        "Oscar Grammy award winner 2025 2026",
        "box office record movie 2025",
        "music album release platinum 2025",
        "major sports championship winner 2025",
        "viral social media controversy 2025",
        "streaming platform subscriber milestone 2025",
    ],
}

SEARCH_INSTRUCTION_TEMPLATE = """You are building a forecasting dataset of RESOLVED binary questions.

TODAY: {current_date}

TASK: Search the web for **major resolved events** in the domain "{domain}" from the past 6-12 months.
Generate {num_questions} binary (YES/NO) forecast questions about events that ALREADY HAPPENED.

SEARCH QUERIES TO USE:
{search_queries}

CRITICAL RULES:
1. SEARCH FIRST — use web_search for EACH query above, then web_fetch interesting results
2. ONLY create questions about events with VERIFIED outcomes you found in search results
3. ground_truth MUST be YES or NO — NEVER leave it empty or unknown
4. resolution_date MUST be in the PAST (before {current_date})
5. resolution_reasoning MUST cite specific evidence from your search
6. If you cannot verify an outcome, DO NOT create a question for it
7. estimated_start_time: when the event was first publicly discussed
8. Alternate YES and NO answers to avoid bias

QUESTION FORMAT:
- "Will X happen by [date]?" (future tense, as if asking before the event)
- Broad appeal — elections, major companies, policy, health, science breakthroughs
- Skip niche/insider topics

QUALITY BAR:
- Each question must have a CLEAR, VERIFIABLE answer found in search results
- resolution_reasoning must be 1-2 sentences citing the source
- estimated_start_time must be meaningfully before resolution_date
"""


async def phase2b_web_search(db_path: str, existing_domains: Counter) -> list:
    """Phase 2B: Search web for resolved events to generate questions with verified GT."""
    print("\n" + "=" * 60)
    print("  PHASE 2B: Web Search for Resolved Events")
    print("=" * 60)

    from src.agents.factory import AgentFactory
    from src.tools import QuestionGeneratorTool
    from src.tools.inspectors.article_retrieval import ArticleRetrievalTool
    from src.core.collectors import ResultCollector

    domain_targets = {
        "health": 10, "climate": 8, "science": 8,
        "finance": 8, "business": 6, "culture": 6,
    }

    needed_per_domain = {}
    for d, target in domain_targets.items():
        current = existing_domains.get(d, 0)
        gap = max(0, target - current)
        if gap > 0:
            needed_per_domain[d] = gap

    print(f"  Domain gaps: {needed_per_domain}")
    total_needed = sum(needed_per_domain.values())
    if total_needed == 0:
        print("  All domains covered!")
        return []

    current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    all_questions = []

    for domain, num_needed in needed_per_domain.items():
        if num_needed <= 0:
            continue

        print(f"\n  --- Searching {domain} (need {num_needed}) ---")

        queries = SEARCH_TOPICS.get(domain, [f"{domain} major event resolved 2025 2026"])
        search_queries = "\n".join(f"  - {q}" for q in queries)

        instruction = SEARCH_INSTRUCTION_TEMPLATE.format(
            current_date=current_date,
            domain=domain,
            num_questions=num_needed,
            search_queries=search_queries,
        )

        collector = ResultCollector[Question]()
        question_tool = QuestionGeneratorTool(
            collector=collector,
            require_ground_truth=True,
            existing_question_ids=set(),
        )

        agent = AgentFactory.create_web_agent(
            tools=[question_tool],
            is_code=True,
            max_steps=25,
        )

        try:
            result = agent.run(instruction)
            domain_qs = collector.get_all()

            valid_qs = [q for q in domain_qs if q.ground_truth is not None]
            print(f"  {domain}: generated {len(domain_qs)}, valid (has GT): {len(valid_qs)}")

            for q in valid_qs:
                gt = str(q.ground_truth)[:6]
                print(f"    [{gt:6s}] {q.question_text[:70]}")

            all_questions.extend(valid_qs)

        except Exception as e:
            logger.error(f"Error collecting {domain}: {e}")

    print(f"\n  Total from web search: {len(all_questions)}")
    return all_questions


async def run(args):
    db_path = args.db

    db = GenericDatabase(db_path)
    db.create_table(Question)
    db.create_table(Article)
    db.create_table(Event)
    db.create_table(CausalHypothesis)

    existing = db.get_many(Question)
    existing_ids = {q.id for q in existing}
    print(f"Existing questions in DB: {len(existing)}")

    all_new = []

    if args.phase in ("1", "all"):
        poly_qs = await phase1_polymarket(db_path)
        new_poly = [q for q in poly_qs if q.id not in existing_ids]
        print(f"\n  New Polymarket questions (not in DB): {len(new_poly)}")

        for q in new_poly:
            try:
                db.save(Question, q)
                all_new.append(q)
                existing_ids.add(q.id)
            except Exception as e:
                logger.debug(f"Save error (likely duplicate): {e}")

        print(f"  Saved {len(all_new)} Polymarket questions to {db_path}")

    if args.phase in ("2", "all"):
        all_existing = db.get_many(Question)
        existing_domains = Counter()
        for q in all_existing:
            d = q.domain.value if hasattr(q.domain, "value") else str(q.domain)
            existing_domains[d] += 1

        print(f"\n  Current domain distribution: {dict(existing_domains)}")

        news_qs = await phase2_news(db_path, existing_domains)
        new_news = [q for q in news_qs if q.id not in existing_ids]
        saved_count = 0
        for q in new_news:
            try:
                db.save(Question, q)
                all_new.append(q)
                existing_ids.add(q.id)
                saved_count += 1
            except Exception as e:
                logger.debug(f"Save error: {e}")

        print(f"  Saved {saved_count} news questions to {db_path}")

    if args.phase == "2b":
        all_existing = db.get_many(Question)
        existing_domains = Counter()
        for q in all_existing:
            d = q.domain.value if hasattr(q.domain, "value") else str(q.domain)
            existing_domains[d] += 1

        print(f"\n  Current domain distribution: {dict(existing_domains)}")

        web_qs = await phase2b_web_search(db_path, existing_domains)
        saved_count = 0
        for q in web_qs:
            if q.id not in existing_ids:
                try:
                    db.save(Question, q)
                    all_new.append(q)
                    existing_ids.add(q.id)
                    saved_count += 1
                except Exception as e:
                    logger.debug(f"Save error: {e}")

        print(f"  Saved {saved_count} web-search questions to {db_path}")

    final = db.get_many(Question)
    print_distribution(final, "FINAL DATASET")

    print(f"\n  Total in DB: {len(final)}")
    print(f"  New this run: {len(all_new)}")


def main():
    parser = argparse.ArgumentParser(description="Collect MoFE binary dataset")
    parser.add_argument("--db", default="mofe_dataset.db")
    parser.add_argument("--phase", choices=["1", "2", "2b", "all"], default="all",
                        help="1=Polymarket, 2=News RSS, 2b=Web search resolved events, all=1+2")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
