"""
CLI script to run deep causal analysis with the HindsightAgent multi-agent system.

This script demonstrates how to build deep causal explanations using managed agents
that can self-evaluate and iterate to create multi-hop causal chains.

Prerequisites:
1. Set up config/local.yaml with LLM API keys
2. Optionally have a resolved question in the database, or provide via CLI

Usage:
    # Analyze a question from the database
    python examples/deep_causal_analysis.py --question-id pm_election_example

    # Create a custom question
    python examples/deep_causal_analysis.py \
        --question "Will Donald Trump win the 2024 US Presidential Election?" \
        --ground-truth true \
        --resolution-date "2024-11-06"

    # Custom configuration
    python examples/deep_causal_analysis.py \
        --question-id my_question \
        --db test.db \
        --max-steps 40 \
        --min-depth 3

Note:
    Uses the HindsightAgent with managed sub-agents (evidence_collector, causal_analyzer)
    to build graphs with 3+ levels instead of shallow 1-level star graphs.
"""

import argparse
import asyncio
from datetime import datetime, timezone
from src.agents.hindsight_agent import HindsightAgent
from src.domain.models import Question, QuestionType, Domain
from src.core.database import Database, GenericDatabase
from src.config import get_config
from src.utils.logging import logger
from src.utils.enums import enum_to_list


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run deep causal analysis using HindsightAgent multi-agent system."
    )

    # Database configuration
    parser.add_argument('--db', type=str, default='test.db',
                       help='Path to database file (default: test.db)')

    # Question source (either from DB or custom)
    question_group = parser.add_mutually_exclusive_group(required=True)
    question_group.add_argument('--question-id', type=str,
                                help='Question ID to load from database')
    question_group.add_argument('--question', type=str,
                                help='Custom question text (requires --ground-truth and --resolution-date)')

    # Custom question parameters (required if --question is used)
    parser.add_argument('--ground-truth', type=str,
                       help='Ground truth answer (true/false for boolean, or value)')
    parser.add_argument('--resolution-date', type=str,
                       help='Resolution date in ISO format (YYYY-MM-DD)')
    parser.add_argument('--question-type', type=str, default='boolean',
                       choices=enum_to_list(QuestionType),
                       help='Type of question (default: boolean)')
    parser.add_argument('--domain', type=str, default='politics',
                       choices=enum_to_list(Domain),
                       help='Question domain (default: politics)')
    parser.add_argument('--difficulty', type=int, default=4, choices=[1, 2, 3, 4, 5],
                       help='Question difficulty 1-5 (default: 4)')

    # Agent configuration
    parser.add_argument('--max-steps', type=int, default=30,
                       help='Maximum steps for manager agent (default: 30)')
    parser.add_argument('--min-depth', type=int, default=3,
                       help='Minimum causal chain depth required (default: 3)')
    parser.add_argument('--min-quality', type=float, default=0.7,
                       help='Minimum quality score required (default: 0.7)')

    # Evidence collection
    parser.add_argument('--evidence-window', type=int, default=90,
                       help='Days before resolution to collect evidence (default: 90)')
    parser.add_argument('--min-articles', type=int, default=5,
                       help='Minimum evidence articles required (default: 5)')

    # Output control
    parser.add_argument('--verbose', action='store_true',
                       help='Show detailed output and visualization')
    parser.add_argument('--skip-visualization', action='store_true',
                       help='Skip graph visualization after completion')

    return parser.parse_args()


async def run_deep_causal_analysis(args):
    """Run deep causal analysis with HindsightAgent.

    Args:
        args: Parsed command line arguments
    """
    # Load configuration
    app_config = get_config()
    db = Database(args.db)

    # Get or create question
    if args.question_id:
        # Load from database
        question = db.db.get(Question, args.question_id)
        if not question:
            logger.error(f"Question '{args.question_id}' not found in database")
            return
        logger.info(f"Loaded question from database: {args.question_id}")
    else:
        # Validate custom question parameters
        if not args.ground_truth or not args.resolution_date:
            logger.error("--ground-truth and --resolution-date are required when using --question")
            return

        # Parse ground truth
        if args.question_type == 'boolean':
            ground_truth = args.ground_truth.lower() == 'true'
        else:
            ground_truth = args.ground_truth

        # Parse resolution date
        try:
            resolution_date = datetime.fromisoformat(args.resolution_date)
            if resolution_date.tzinfo is None:
                resolution_date = resolution_date.replace(tzinfo=timezone.utc)
        except ValueError as e:
            logger.error(f"Invalid resolution date format: {e}")
            return

        # Create custom question
        question_id = f"custom_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        question = Question(
            id=question_id,
            question_text=args.question,
            question_type=QuestionType(args.question_type),
            domain=Domain(args.domain),
            difficulty=args.difficulty,
            source="custom",
            resolution_date=resolution_date,
            ground_truth=ground_truth,
        )

        # Save to database
        db.save_question(question)
        logger.info(f"Created custom question: {question_id}")

    # Log configuration
    logger.info("=" * 80)
    logger.info("Deep Causal Analysis - HindsightAgent Multi-Agent System")
    logger.info("=" * 80)
    logger.info(f"Database: {args.db}")
    logger.info(f"Question ID: {question.id}")
    logger.info(f"Question: {question.question_text}")
    logger.info(f"Ground Truth: {question.ground_truth}")
    logger.info(f"Resolution Date: {question.resolution_date}")
    logger.info(f"Agent max steps: {args.max_steps}")
    logger.info(f"Min depth: {args.min_depth}")
    logger.info(f"Min quality: {args.min_quality}")
    logger.info("")

    # Initialize HindsightAgent
    agent = HindsightAgent(db_path=args.db, max_steps=args.max_steps)

    # Construct prompt
    prompt = f"""
Your task: Build a DEEP causal explanation for this question with hindsight.

QUESTION ID: {question.id}
QUESTION: {question.question_text}
RESOLUTION DATE: {question.resolution_date}
GROUND TRUTH: {question.ground_truth}

CRITICAL: When using tools, ALWAYS use question_id="{question.id}"

REQUIREMENTS:
- Causal graph depth must be >= {args.min_depth} levels (multi-hop chains)
- Each causal link must have supporting evidence
- Build from root causes → intermediate factors → immediate causes → outcome

PROCESS:

1. COLLECT EVIDENCE:
   Call evidence_collector to gather relevant articles:
   - Time window: {args.evidence_window} days before resolution
   - Need at least {args.min_articles} high-quality articles
   - If insufficient, ask agent to broaden search

2. BUILD DEEP CAUSAL GRAPH:
   Call causal_analyzer with this exact prompt:

   "Build a deep causal graph for question '{question.id}' about: {question.question_text}

   CRITICAL: When calling event_identifier and causal_reasoner tools,
   use question_id='{question.id}' (not any other ID!).

   Steps:
   1. Create target event (the outcome from ground truth)
   2. Identify 3-4 immediate causes (level 1)
   3. For EACH immediate cause, identify what caused IT (level 2)
   4. For top 2 level-2 causes, go even deeper (level 3)
   5. Use graph_inspector(question_id='{question.id}') to check depth
   6. If depth < {args.min_depth}, create more intermediate events

   REMEMBER: Every causal_reasoner call must have question_id='{question.id}'"

3. EVALUATE & ITERATE:
   - Call graph_inspector(question_id='{question.id}') to check current depth
   - If max_depth < {args.min_depth}: Tell causal_analyzer to go deeper
   - Target: {args.min_articles}+ events, {args.min_depth}+ levels, quality > {args.min_quality}

4. FINAL VALIDATION:
   - Verify each causal link has evidence support
   - Check temporal validity (causes before effects)
   - Confirm chains explain the ground truth outcome

SUCCESS CRITERIA:
✓ Evidence: {args.min_articles}+ relevant articles collected
✓ Depth: Causal chains with {args.min_depth}+ levels
✓ Events: 5+ events created
✓ Links: Multiple causal chains to target
✓ Quality: Score > {args.min_quality}

Begin the analysis!
"""

    # Run agent
    try:
        logger.info("Starting multi-agent causal analysis...")
        logger.info("=" * 80)

        # Run in thread pool to avoid blocking
        result = await asyncio.to_thread(agent.run, prompt)

        logger.info("=" * 80)
        logger.info("ANALYSIS COMPLETED")
        logger.info("=" * 80)

        if args.verbose:
            logger.info("\nAgent Output:")
            logger.info(result)

        # Visualize results
        if not args.skip_visualization:
            logger.info("\n" + "=" * 80)
            logger.info("CAUSAL GRAPH VISUALIZATION")
            logger.info("=" * 80)
            visualize_causal_graph(question.id, args.db, verbose=args.verbose)

    except Exception as e:
        logger.error("=" * 80)
        logger.error("ANALYSIS FAILED")
        logger.error("=" * 80)
        logger.error(f"Error: {e}")

        if args.verbose:
            import traceback
            logger.error(traceback.format_exc())

        raise


def visualize_causal_graph(question_id: str, db_path: str, verbose: bool = False):
    """Visualize the causal graph built for a question.

    Args:
        question_id: Question ID to visualize
        db_path: Database path
        verbose: Show detailed output
    """
    from src.domain.models import CausalHypothesis, Event, Article
    from collections import defaultdict

    db = GenericDatabase(db_path)

    # Get all data
    all_hypotheses = db.get_many(CausalHypothesis)
    all_events = db.get_many(Event)
    all_articles = db.get_many(Article)

    # Filter for this question
    question_hypotheses = [
        h for h in all_hypotheses
        if question_id in h.discovered_by_question_ids
    ]

    if verbose:
        logger.info(f"\n🔍 DATABASE CONTENTS:")
        logger.info(f"  Total Articles: {len(all_articles)}")
        logger.info(f"  Total Events: {len(all_events)}")
        logger.info(f"  Total Hypotheses: {len(all_hypotheses)}")
        logger.info(f"  Hypotheses for this question: {len(question_hypotheses)}")

    if not question_hypotheses:
        logger.warning(f"\n❌ No causal graph found for question {question_id}")
        logger.warning(f"\nPossible issues:")
        logger.warning(f"  1. Agent didn't complete causal analysis")
        logger.warning(f"  2. Hypotheses weren't persisted to database")
        logger.warning(f"  3. Question ID mismatch in tool calls")
        return

    # Get all events
    event_ids = set()
    for h in question_hypotheses:
        event_ids.add(h.source_event_id)
        event_ids.add(h.target_event_id)

    events = {evt.id: evt for evt in all_events if evt.id in event_ids}

    logger.info(f"\n📊 GRAPH SUMMARY")
    logger.info(f"Events: {len(events)}")
    logger.info(f"Causal Links: {len(question_hypotheses)}")

    # Display events
    if verbose:
        logger.info(f"\n📍 EVENTS:")
        for evt_id, evt in events.items():
            logger.info(f"  [{evt_id}]")
            logger.info(f"    Title: {evt.title}")
            logger.info(f"    Type: {evt.event_type.value if evt.event_type else 'N/A'}")
            logger.info(f"    Date: {evt.occurred_date or evt.predicted_date}")

    # Display causal chains
    logger.info(f"\n🔗 CAUSAL CHAINS:")
    for i, hyp in enumerate(question_hypotheses, 1):
        source = events.get(hyp.source_event_id)
        target = events.get(hyp.target_event_id)

        source_title = source.title if source else hyp.source_event_id
        target_title = target.title if target else hyp.target_event_id

        logger.info(f"\n  {i}. {source_title}")
        logger.info(f"     ↓ {hyp.relation_type.value} (conf: {hyp.confidence:.2f}, str: {hyp.strength:.2f})")
        logger.info(f"     {target_title}")

        if verbose:
            logger.info(f"     Reasoning: {hyp.reasoning[:150]}...")
            if hyp.evidence_article_ids:
                logger.info(f"     Evidence: {len(hyp.evidence_article_ids)} articles")

    # Calculate depth
    graph = defaultdict(list)
    for hyp in question_hypotheses:
        graph[hyp.target_event_id].append(hyp.source_event_id)

    def find_max_depth(node, visited=None):
        if visited is None:
            visited = set()
        if node in visited or node not in graph:
            return 0
        visited.add(node)
        max_child = 0
        for source in graph[node]:
            depth = find_max_depth(source, visited.copy())
            max_child = max(max_child, depth)
        return 1 + max_child

    # Find target event and calculate depth
    question_obj = db.get(Question, question_id)
    max_depth = 0

    # Try to get target from question
    target_event_id = question_obj.target_event_id if question_obj else None

    # If not set, detect automatically (event with incoming links but fewest outgoing links)
    if not target_event_id:
        # Find all events that appear as targets
        all_targets = set(h.target_event_id for h in question_hypotheses)
        all_sources = set(h.source_event_id for h in question_hypotheses)

        # Target event should be something that's a target but rarely/never a source
        # Count how many times each event appears as a source
        source_counts = {}
        for event_id in all_targets:
            source_counts[event_id] = sum(1 for h in question_hypotheses if h.source_event_id == event_id)

        # Pick the one that's a target but appears least as a source
        if source_counts:
            target_event_id = min(source_counts, key=source_counts.get)
            logger.info(f"Auto-detected target event: {target_event_id} (appears {source_counts[target_event_id]} times as source)")

    if target_event_id:
        max_depth = find_max_depth(target_event_id)

    # Calculate metrics
    avg_conf = sum(h.confidence for h in question_hypotheses) / len(question_hypotheses)
    avg_str = sum(h.strength for h in question_hypotheses) / len(question_hypotheses)
    with_evidence = sum(1 for h in question_hypotheses if h.evidence_article_ids)

    logger.info(f"\n{'='*80}")
    logger.info(f"📊 GRAPH METRICS")
    logger.info(f"{'='*80}")
    logger.info(f"Maximum Causal Depth: {max_depth} levels")
    logger.info(f"Total Events: {len(events)}")
    logger.info(f"Total Links: {len(question_hypotheses)}")
    logger.info(f"Average Confidence: {avg_conf:.2f}")
    logger.info(f"Average Strength: {avg_str:.2f}")
    logger.info(f"Links with Evidence: {with_evidence}/{len(question_hypotheses)}")

    # Depth assessment
    if max_depth >= 3:
        logger.info(f"✓ Graph is DEEP ({max_depth} levels) - Excellent!")
    elif max_depth == 2:
        logger.info(f"⚠ Graph has moderate depth ({max_depth} levels) - Could be deeper")
    else:
        logger.info(f"❌ Graph is SHALLOW ({max_depth} level) - Needs improvement")

    logger.info(f"{'='*80}\n")


def main():
    """Main entry point."""
    args = parse_args()
    asyncio.run(run_deep_causal_analysis(args))


if __name__ == "__main__":
    main()
