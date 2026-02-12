"""Integration test for Evidence Pipeline.

NOTE: This is a structural test that validates the pipeline can be instantiated
and configured correctly. Full end-to-end testing requires:
1. Resolved questions in the database
2. LLM API access for evidence collection and causal reasoning
3. Events in the database to link to

For full testing, use manual runs with real data.
"""

import sys

# Set UTF-8 encoding for Windows console output
if sys.platform == "win32":
    import codecs

    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "ignore")
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "ignore")

import pytest
from datetime import datetime, timezone, timedelta

from src.pipelines.evidence import EvidencePipeline
from src.config.pipeline import EvidencePipelineConfig
from src.config import DatabaseConfig
from src.domain.models import (
    Question,
    Article,
    Event,
    EventType,
    EventStatus,
    QuestionType,
)
from src.core.database import GenericDatabase


@pytest.mark.integration
@pytest.mark.asyncio
async def test_evidence_pipeline_initialization(test_db_path):
    """Test that Evidence Pipeline can be initialized correctly."""
    print("\n" + "=" * 80)
    print("Test: Evidence Pipeline Initialization")
    print("=" * 80)

    # Configure pipeline
    evidence_config = EvidencePipelineConfig(
        evidence_window_days=30,
        min_evidence_articles=3,
        causal_confidence_threshold=0.6,
        causal_strength_threshold=0.3,
    )

    db_config = DatabaseConfig(
        db_path=test_db_path,
        batch_size=10,
    )

    # Create pipeline
    print("\n1. Creating pipeline...")
    pipeline = EvidencePipeline(
        evidence_config=evidence_config,
        database_config=db_config,
        enable_persistence=True,
    )

    # Validate pipeline structure
    print("\n2. Validating pipeline structure...")
    assert pipeline.name == "EvidencePipeline"
    assert len(pipeline.stages) == 4, "Should have 4 stages"

    print("   - Stage 1: HindsightEvidenceCollection")
    assert pipeline.evidence_stage.name == "HindsightEvidenceCollection"

    print("   - Stage 1.5: TargetEventIdentification")
    assert pipeline.target_event_stage.name == "TargetEventIdentification"

    print("   - Stage 2: CausalReasoning")
    assert pipeline.reasoning_stage.name == "CausalReasoning"

    print("   - Stage 3: CausalGraphBuilding")
    assert pipeline.graph_stage.name == "CausalGraphBuilding"

    print("   [OK] All stages initialized")

    # Validate configuration
    print("\n3. Validating configuration...")
    assert pipeline.evidence_config.evidence_window_days == 30
    assert pipeline.evidence_config.min_evidence_articles == 3
    assert pipeline.evidence_config.causal_confidence_threshold == 0.6
    print("   [OK] Configuration correct")

    print("\n[PASS] Evidence Pipeline Initialization Test")
    print("=" * 80)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_evidence_pipeline_with_no_resolved_questions(test_db_path):
    """Test pipeline behavior when no resolved questions exist."""
    print("\n" + "=" * 80)
    print("Test: Evidence Pipeline with No Resolved Questions")
    print("=" * 80)

    # Configure pipeline
    evidence_config = EvidencePipelineConfig()
    db_config = DatabaseConfig(db_path=test_db_path)

    pipeline = EvidencePipeline(
        evidence_config=evidence_config,
        database_config=db_config,
        enable_persistence=False,  # Disable for this test
    )

    print("\n1. Running pipeline with empty database...")
    results = await pipeline.run()

    print("\n2. Validating results...")
    assert len(results) == 0 or results[0].items_output == 0
    assert len(pipeline.resolved_questions) == 0
    assert len(pipeline.evidence_articles) == 0
    assert len(pipeline.causal_hypotheses) == 0

    print("   [OK] Pipeline handled empty input gracefully")

    print("\n[PASS] Empty Input Test")
    print("=" * 80)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_evidence_pipeline_with_mock_resolved_question(test_db_path):
    """Test pipeline with a mock resolved question (structure test only).

    NOTE: This test only validates structure. It will not produce real evidence
    or causal links without LLM access and proper configuration.
    """
    print("\n" + "=" * 80)
    print("Test: Evidence Pipeline with Mock Resolved Question")
    print("=" * 80)

    # Setup database
    db = GenericDatabase(test_db_path)
    db.create_table(Question)
    db.create_table(Event)
    db.create_table(Article)

    # Create a mock event
    print("\n1. Creating mock event...")
    event = Event(
        id="evt_test_001",
        title="Federal Reserve Rate Decision",
        description="The Federal Reserve decided to raise interest rates by 0.25%",
        event_type=EventType.DECISION,
        domain="finance",
        occurred_date=datetime.now(timezone.utc) - timedelta(days=10),
        resolution_date=datetime.now(timezone.utc) - timedelta(days=10),
        status=EventStatus.OCCURRED,
        outcome_verified=True,
    )
    db.save(Event, event)
    print(f"   - Created event: {event.id}")

    # Create a mock resolved question
    print("\n2. Creating mock resolved question...")
    question = Question(
        id="q_test_001",
        question_text="Will the Federal Reserve raise interest rates in June 2024?",
        question_type=QuestionType.BINARY,
        domain="finance",
        difficulty=3,
        resolution_date=datetime.now(timezone.utc) - timedelta(days=10),
        ground_truth=True,
        outcome_event_ids=[event.id],
        source="test",  # Required field for test
    )
    db.save(Question, question)
    print(f"   - Created question: {question.id}")

    # Configure pipeline
    evidence_config = EvidencePipelineConfig(
        evidence_window_days=30,
        min_evidence_articles=2,
        min_resolution_age_days=1,  # Allow recently resolved questions
    )
    db_config = DatabaseConfig(db_path=test_db_path)

    pipeline = EvidencePipeline(
        evidence_config=evidence_config,
        database_config=db_config,
        enable_persistence=False,  # Disable to avoid persisting incomplete data
    )

    print("\n3. Loading resolved questions from database...")
    resolved_questions = pipeline._load_resolved_questions()
    print(f"   - Found {len(resolved_questions)} resolved questions")

    assert len(resolved_questions) == 1
    assert resolved_questions[0].id == question.id
    print("   [OK] Question loaded successfully")

    # Note: We stop here because actually running the pipeline requires:
    # - LLM API access (for web_search and causal reasoning)
    # - Real web sources or mock articles
    # - Proper agent configuration

    print("\n4. Getting pipeline summary...")
    pipeline.resolved_questions = resolved_questions
    summary = pipeline.get_summary()

    print(f"   - Resolved questions: {summary['resolved_questions']}")
    print(f"   - Evidence articles: {summary['evidence_articles']}")
    print(f"   - Causal hypotheses: {summary['causal_hypotheses']}")

    assert summary["resolved_questions"] == 1
    print("   [OK] Summary generated correctly")

    print("\n[PASS] Mock Resolved Question Test")
    print("=" * 80)
    print("\nNOTE: For full end-to-end testing with LLM calls:")
    print("1. Set up config/local.yaml with LLM API keys")
    print("2. Create resolved questions in the database")
    print("3. Run: python -m pytest tests/integration/test_evidence_pipeline.py -v -s")


@pytest.mark.integration
def test_evidence_pipeline_stages_configuration(test_db_path):
    """Test that all stages are configured with correct settings."""
    print("\n" + "=" * 80)
    print("Test: Evidence Pipeline Stages Configuration")
    print("=" * 80)

    # Create pipeline with specific configuration
    evidence_config = EvidencePipelineConfig(
        evidence_window_days=45,
        min_evidence_articles=7,
        causal_confidence_threshold=0.7,
        causal_strength_threshold=0.4,
        require_evidence=True,
        allow_causal_cycles=False,
        validate_temporal_ordering=True,
        max_links_per_event=15,
    )

    db_config = DatabaseConfig(db_path=test_db_path)

    pipeline = EvidencePipeline(
        evidence_config=evidence_config,
        database_config=db_config,
        enable_persistence=False,
    )

    print("\n1. Checking Stage 1 configuration...")
    assert pipeline.evidence_stage.config.evidence_window_days == 45
    assert pipeline.evidence_stage.config.min_evidence_articles == 7
    print("   [OK] Evidence collection configured correctly")

    print("\n2. Checking Stage 2 configuration...")
    assert pipeline.reasoning_stage.config.min_confidence == 0.7
    assert pipeline.reasoning_stage.config.min_strength == 0.4
    assert pipeline.reasoning_stage.config.require_evidence is True
    print("   [OK] Causal reasoning configured correctly")

    print("\n3. Checking Stage 3 configuration...")
    assert pipeline.graph_stage.config.allow_cycles is False
    assert pipeline.graph_stage.config.validate_temporal_ordering is True
    assert pipeline.graph_stage.config.max_links_per_event == 15
    print("   [OK] Graph building configured correctly")

    print("\n[PASS] Stages Configuration Test")
    print("=" * 80)
