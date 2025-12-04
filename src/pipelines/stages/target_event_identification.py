"""Target event identification stage - creates/identifies target events for questions."""

import asyncio
from typing import List, Tuple, Optional
from datetime import datetime, timezone
import uuid
import hashlib

from pydantic import BaseModel, Field

from src.pipelines.base import PipelineStage
from src.domain.models import Question, Event, Article
from src.domain.models.domain import Domain
from src.domain.models.event import EventType, EventStatus
from src.core.database import GenericDatabase
from src.utils.logging import logger
from src.utils.usage_tracking import UsageTracker, log_usage
from src.llm import LiteLLMClient
from src.config import get_config


class TargetEventIdentificationConfig(BaseModel):
    """Configuration for target event identification."""

    similarity_threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Similarity threshold for matching existing events"
    )
    create_if_not_found: bool = Field(
        default=True,
        description="Create new event if no match found"
    )


class TargetEventIdentificationStage(PipelineStage[Tuple[Question, List[Article]], Question]):
    """Identifies or creates target events for questions without them.
    
    This stage:
    1. Takes questions that have no target_event_id (e.g., from Polymarket)
    2. Uses ground truth + question text to identify what event occurred
    3. Searches for matching existing events
    4. Creates new target event if needed
    5. Updates the question with target_event_id
    
    Example transformations:
    - "Will Bitcoin reach $100k by Dec 31, 2024?" (resolved=True)
      → Event: "Bitcoin reaches $100,000 USD"
    - "Will Trump win the 2024 election?" (resolved=True)  
      → Event: "Donald Trump wins 2024 US Presidential Election"
    """

    def __init__(
        self,
        config: TargetEventIdentificationConfig,
        db_path: str = "worldreasoner.db"
    ):
        """Initialize target event identification stage.

        Args:
            config: Configuration
            db_path: Path to database
        """
        super().__init__(name="TargetEventIdentification", config=config)
        self.db = GenericDatabase(db_path)
        self.usage_tracker = UsageTracker()
        
        # Initialize LLM client
        app_config = get_config()
        self.llm_client = LiteLLMClient(app_config.llm)

    async def process(
        self,
        inputs: List[Tuple[Question, List[Article]]]
    ) -> List[Question]:
        """Identify target events for questions.

        Args:
            inputs: List of (Question, List[Article]) tuples

        Returns:
            List of updated questions with target_event_id
        """
        logger.info(f"Identifying target events for {len(inputs)} questions")

        updated_questions = []

        for idx, (question, evidence_articles) in enumerate(inputs, 1):
            # Skip if question already has a target event
            if question.target_event_id:
                logger.debug(f"[{idx}/{len(inputs)}] Question {question.id} already has target event")
                updated_questions.append(question)
                continue

            # Skip if question is not resolved
            if question.ground_truth is None:
                logger.debug(f"[{idx}/{len(inputs)}] Question {question.id} not resolved, skipping")
                updated_questions.append(question)
                continue

            logger.info(f"[{idx}/{len(inputs)}] Identifying target event for: {question.id}")

            try:
                # Identify or create target event
                target_event_id = await self._identify_target_event(
                    question, evidence_articles
                )

                if target_event_id:
                    # Update question
                    question.target_event_id = target_event_id
                    self.db.save(Question, question)
                    logger.info(f"Updated question {question.id} with target_event_id: {target_event_id}")
                else:
                    logger.warning(f"Could not identify target event for {question.id}")

                updated_questions.append(question)

            except Exception as e:
                logger.error(f"Failed to identify target event for {question.id}: {e}")
                updated_questions.append(question)
                continue

        # Log usage summary
        if self.usage_tracker.total_calls > 0:
            self.usage_tracker.log_summary(context="TargetEventIdentification")

        return updated_questions

    async def _identify_target_event(
        self,
        question: Question,
        evidence_articles: List[Article]
    ) -> Optional[str]:
        """Identify or create target event for a question.

        Args:
            question: Question to analyze
            evidence_articles: Evidence articles

        Returns:
            Event ID or None
        """
        # Use LLM to extract event description from question + ground truth
        event_description = await self._extract_event_description(question)
        
        if not event_description:
            logger.warning(f"Could not extract event description from {question.id}")
            return None

        # Search for existing matching event
        existing_event = self._find_matching_event(
            event_description, question, evidence_articles
        )

        if existing_event:
            logger.info(f"Found matching event: {existing_event.id} for question {question.id}")
            return existing_event.id

        # Create new event if configured
        if self.config.create_if_not_found:
            new_event = self._create_target_event(
                event_description, question, evidence_articles
            )
            self.db.save(Event, new_event)
            logger.info(f"Created new target event: {new_event.id} for question {question.id}")
            return new_event.id

        return None

    async def _extract_event_description(self, question: Question) -> Optional[str]:
        """Use LLM to extract event description from question.

        Args:
            question: Question to analyze

        Returns:
            Event description or None
        """
        # Create instruction
        instruction = self._build_extraction_instruction(question)

        try:
            # Call LLM using the client
            messages = [{"role": "user", "content": instruction}]
            result = await self.llm_client.acomplete(messages)
            
            # Parse result
            event_description = self._parse_event_description(result)
            return event_description

        except Exception as e:
            logger.error(f"Failed to extract event description: {e}")
            return Nonet_description

        except Exception as e:
            logger.error(f"Failed to extract event description: {e}")
            return None

    def _build_extraction_instruction(self, question: Question) -> str:
        """Build instruction for event extraction.

        Args:
            question: Question to analyze

        Returns:
            Instruction string
        """
        ground_truth_str = str(question.ground_truth)
        
        return f"""You are analyzing a resolved forecast question to identify the target event (what actually happened).

Question: {question.question_text}
Question Type: {question.question_type.value}
Ground Truth: {ground_truth_str}
Resolution Date: {question.resolution_date.strftime('%Y-%m-%d')}
Domain: {question.domain.value}

Based on this information, describe the EVENT that occurred (or didn't occur) in a clear, factual way.

Guidelines:
- Be specific and concrete
- Use past tense (the event already happened or didn't happen)
- Focus on WHAT happened, not WHY
- Keep it under 150 characters
- If ground_truth is False/No, phrase it as "X did NOT happen" or describe what happened instead

Examples:
Question: "Will Bitcoin reach $100,000 by Dec 31, 2024?"
Ground Truth: True
→ "Bitcoin reaches $100,000 USD"

Question: "Will Donald Trump win the 2024 US Presidential Election?"
Ground Truth: True
→ "Donald Trump wins 2024 US Presidential Election"

Question: "Will there be a recession in 2024?"
Ground Truth: False
→ "No recession occurs in 2024"

Now extract the target event for the given question. Respond with ONLY the event description, nothing else.
"""

    def _parse_event_description(self, result: str) -> Optional[str]:
        """Parse event description from LLM result.

        Args:
            result: LLM output

        Returns:
            Event description or None
        """
        # Clean up the result
        description = result.strip()
        
        # Remove common prefixes
        prefixes = [
            "Event description:", "Target event:", "Event:", 
            "The event is:", "Output:"
        ]
        for prefix in prefixes:
            if description.lower().startswith(prefix.lower()):
                description = description[len(prefix):].strip()

        # Validate length
        if len(description) < 10 or len(description) > 200:
            logger.warning(f"Event description has invalid length: {len(description)}")
            return None

        return description

    def _find_matching_event(
        self,
        event_description: str,
        question: Question,
        evidence_articles: List[Article]
    ) -> Optional[Event]:
        """Find existing event matching the description.

        Args:
            event_description: Event description to match
            question: Question being analyzed
            evidence_articles: Evidence articles

        Returns:
            Matching event or None
        """
        # Get all events in same domain
        all_events = self.db.get_many(Event, filters={'domain': question.domain})

        # Filter by temporal proximity (within 30 days of resolution)
        time_window_days = 30
        candidates = []
        
        for event in all_events:
            if not event.occurred_date:
                continue
                
            # Check if event occurred near question resolution
            time_diff = abs((event.occurred_date - question.resolution_date).days)
            if time_diff <= time_window_days:
                candidates.append(event)

        if not candidates:
            logger.debug(f"No temporal candidates found for {question.id}")
            return None

        # Simple text similarity matching
        best_match = None
        best_score = 0.0

        for event in candidates:
            score = self._calculate_similarity(event_description, event.title)
            if score > best_score and score >= self.config.similarity_threshold:
                best_score = score
                best_match = event

        if best_match:
            logger.info(f"Found match with score {best_score:.2f}: {best_match.id}")

        return best_match

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate simple text similarity.

        Args:
            text1: First text
            text2: Second text

        Returns:
            Similarity score 0.0-1.0
        """
        # Simple word overlap similarity
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        
        if not words1 or not words2:
            return 0.0

        intersection = words1.intersection(words2)
        union = words1.union(words2)

        return len(intersection) / len(union) if union else 0.0

    def _create_target_event(
        self,
        event_description: str,
        question: Question,
        evidence_articles: List[Article]
    ) -> Event:
        """Create new target event.

        Args:
            event_description: Event description
            question: Question being analyzed
            evidence_articles: Evidence articles

        Returns:
            New Event instance
        """
        # Generate event ID
        event_hash = hashlib.sha256(
            f"{event_description}_{question.resolution_date}".encode()
        ).hexdigest()[:8]
        
        event_id = f"evt_{question.domain.value}_{question.resolution_date.strftime('%Y%m%d')}_{event_hash}"

        # Determine event type based on question type and domain
        event_type = EventType.OUTCOME  # Most forecast questions are about outcomes
        
        # Determine status based on ground truth
        if question.ground_truth is False:
            status = EventStatus.CANCELLED  # Event didn't happen
        else:
            status = EventStatus.OCCURRED  # Event happened

        # Create event with all required fields
        event = Event(
            id=event_id,
            title=event_description[:200],  # Truncate for title
            description=f"Target event for question: {question.question_text}. Ground truth: {question.ground_truth}",
            event_type=event_type,
            domain=question.domain,
            status=status,
            occurred_date=question.resolution_date if question.ground_truth is not False else None,
            resolution_date=question.resolution_date,
            article_ids=[a.id for a in evidence_articles[:5]],  # Link to evidence
            metadata={
                'created_from_question': question.id,
                'source': 'target_event_identification',
                'ground_truth': question.ground_truth,
            }
        )

        return event
