"""Hindsight evidence collection stage for Evidence Pipeline."""

from typing import List
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, Field

from src.pipelines.base import PipelineStage
from src.domain.models import Question, Article
from src.agents.factory import AgentFactory
from src.pipelines.stages.tools import ArticleCollectorTool
from src.pipelines.stages.collectors import ResultCollector
from src.pipelines.prompts import HindsightAnalysisPrompts
from src.utils.logging import logger


class EvidenceCollectionConfig(BaseModel):
    """Configuration for evidence collection."""

    evidence_window_days: int = Field(
        default=30,
        description="Days before resolution to collect evidence (causal factors)"
    )
    min_evidence_articles: int = Field(
        default=5,
        description="Minimum articles to collect per question"
    )
    include_expert_analysis: bool = Field(
        default=True,
        description="Prioritize analysis articles discussing causal factors"
    )


class HindsightEvidenceCollectionStage(PipelineStage[Question, Article]):
    """Collects evidence articles published BEFORE event resolution.

    This stage uses hindsight (knowing the outcome) to intelligently search
    for and identify articles from BEFORE the event that discussed the
    factors that actually caused the outcome.

    Key concept:
    - We have HINDSIGHT (know the outcome that occurred on resolution_date)
    - We search articles from BEFORE resolution_date
    - We look for factors that were present/discussed before the event
    - These pre-event factors are the potential causes we want to identify
    """

    def __init__(
        self,
        config: EvidenceCollectionConfig,
        db_path: str = "worldreasoner.db"
    ):
        """Initialize hindsight evidence collection stage.

        Args:
            config: Evidence collection configuration
            db_path: Path to database for deduplication
        """
        super().__init__(name="HindsightEvidenceCollection", config=config)

        # Create result collector for evidence articles
        self.collector = ResultCollector[Article]()

        # Create ArticleCollectorTool with collector and database
        self.article_tool = ArticleCollectorTool(
            db_path=db_path,
            collector=self.collector
        )

        # Create WebAgent with article collection tool
        self.web_agent = AgentFactory.create_web_agent(tools=[self.article_tool])

        # Prompt generator
        self.prompts = HindsightAnalysisPrompts()

    async def process(self, inputs: List[Question]) -> List[Article]:
        """Collect hindsight evidence for resolved questions.

        Args:
            inputs: List of resolved questions

        Returns:
            List of evidence articles collected
        """
        logger.info(f"Collecting hindsight evidence for {len(inputs)} resolved questions")

        all_articles = []

        for idx, question in enumerate(inputs, 1):
            logger.info(f"[{idx}/{len(inputs)}] Processing question: {question.id}")

            # Validate question is resolved
            if not question.resolution_date:
                logger.warning(f"Question {question.id} has no resolution_date, skipping")
                continue

            if question.ground_truth is None:
                logger.warning(f"Question {question.id} has no ground_truth, skipping")
                continue

            # Check if resolution is too recent (allow time for analysis to be published)
            days_since_resolution = (datetime.now(timezone.utc) - question.resolution_date).days
            if days_since_resolution < 1:
                logger.info(f"Question {question.id} resolved too recently ({days_since_resolution} days), skipping")
                continue

            # Collect evidence for this question
            try:
                articles = await self._collect_evidence_for_question(question)
                all_articles.extend(articles)
                logger.info(f"Collected {len(articles)} evidence articles for {question.id}")
            except Exception as e:
                logger.error(f"Failed to collect evidence for {question.id}: {e}")
                continue

        logger.info(f"Collected total of {len(all_articles)} evidence articles")
        return all_articles

    async def _collect_evidence_for_question(self, question: Question) -> List[Article]:
        """Collect evidence articles for a single resolved question.

        Args:
            question: Resolved question

        Returns:
            List of evidence articles
        """
        # Clear collector before starting
        initial_count = len(self.collector.get_all())

        # Generate evidence collection instruction
        current_date = datetime.now(timezone.utc)
        instruction = self.prompts.get_evidence_collection_instruction(
            current_date=current_date,
            question=question,
            min_articles=self.config.min_evidence_articles,
        )

        # Add temporal context to instruction
        resolution_date_str = question.resolution_date.strftime('%Y-%m-%d')
        start_date = question.resolution_date - timedelta(days=self.config.evidence_window_days)
        start_date_str = start_date.strftime('%Y-%m-%d')

        temporal_guidance = f"""
TEMPORAL CONSTRAINTS:
- Resolution date (when outcome occurred): {resolution_date_str}
- Evidence window: {start_date_str} to {resolution_date_str}
- Only collect articles published BEFORE {resolution_date_str}
- Look for articles discussing factors/events that led up to the outcome
- We have hindsight (know the outcome), but search for pre-event causal factors
"""

        full_instruction = instruction + "\n" + temporal_guidance

        logger.debug(f"Running evidence collection agent for {question.id}")

        try:
            # Run the agent
            result = self.web_agent.run(full_instruction)
            logger.debug(f"Agent completed: {result}")
        except Exception as e:
            logger.error(f"Agent error for {question.id}: {e}")
            # Continue anyway - may have collected some articles

        # Get articles collected during this run
        all_collected = self.collector.get_all()
        new_articles = all_collected[initial_count:]  # Only articles added during this run

        # Tag articles with evidence metadata
        for article in new_articles:
            # Mark as hindsight evidence
            article.metadata['evidence_type'] = 'hindsight'
            article.metadata['related_question_ids'] = [question.id]

            # Link to target event if possible
            if question.target_event_id and question.target_event_id not in article.event_ids:
                article.event_ids.append(question.target_event_id)

        return new_articles
