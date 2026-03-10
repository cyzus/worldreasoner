"""Event review service - LLM-based automatic event verification."""

import json
from datetime import datetime, timezone
from typing import List, Optional, Dict
from pydantic import BaseModel
from rich.console import Console

from src.core.database import GenericDatabase
from src.domain.models import Event, Article, Question, ReviewStatus
from src.domain.models.causal_hypothesis import CausalHypothesis
from src.services.service_base import ServiceBase
from src.core.llm import LiteLLMClient
from src.config.app import LLMConfig
from src.utils.logging import logger
from src.config.settings import get_config
from src.config.pipeline import SATISFACTION_DEFAULTS

console = Console()


class EventReviewCriteria(BaseModel):
    """Criteria for LLM event review."""

    min_events: int = SATISFACTION_DEFAULTS.min_graph_events
    min_depth: int = 1  # Lowered default - causal links may not exist yet
    require_time_coverage: bool = True
    check_factual_accuracy: bool = (
        False  # Disabled by default - causal depth check is expensive
    )
    check_temporal_validity: bool = True


class EventReviewResult(BaseModel):
    """Result of LLM event review."""

    event_id: str
    approved: bool
    confidence: float
    issues: List[str]
    reasoning: str
    suggested_status: str


class EventReviewReport(BaseModel):
    """Aggregated review report for a question's events."""

    question_id: str
    total_events: int
    approved_events: int
    rejected_events: int
    pending_events: int
    event_reviews: List[EventReviewResult]
    overall_assessment: str
    meets_criteria: bool
    criteria_met: Dict[str, bool]
    reviewed_at: datetime


class EventReviewService(ServiceBase):
    """Service for LLM-based automatic event review.

    Reviews agent-generated events for accuracy and quality using LLM judgment.
    Can be used as a first-pass filter before human review, or as a replacement.
    """

    def __init__(
        self,
        db: GenericDatabase,
        llm_config: Optional[LLMConfig] = None,
        review_model: Optional[str] = None,
    ):
        """Initialize the event review service.

        Args:
            db: Database instance
            llm_config: LLM configuration (uses default if not provided)
            review_model: Override model for review (cheaper model recommended)
        """
        super().__init__(db)
        if llm_config is None:
            llm_config = get_config().llm
        if llm_config.review_model:
            llm_config = llm_config.model_copy(
                update={"model": llm_config.review_model}
            )
        if review_model:
            llm_config = llm_config.model_copy(update={"model": review_model})
        print(f"Using review model: {llm_config.model}")
        self.llm_client = LiteLLMClient(llm_config)
        self.criteria = EventReviewCriteria()

    async def review_events_for_question(
        self,
        question_id: str,
        sample_size: Optional[int] = None,
    ) -> EventReviewReport:
        """Review all events for a specific question.

        Args:
            question_id: The question ID to review events for
            sample_size: Optional limit on number of events to review

        Returns:
            EventReviewReport with aggregated results
        """
        events = self.db.get_many(
            Event, filters={"extracted_for_question_id": question_id}
        )

        if not events:
            return EventReviewReport(
                question_id=question_id,
                total_events=0,
                approved_events=0,
                rejected_events=0,
                pending_events=0,
                event_reviews=[],
                overall_assessment="No events found for this question",
                meets_criteria=False,
                criteria_met={},
                reviewed_at=datetime.now(timezone.utc),
            )

        if sample_size and sample_size < len(events):
            events = events[:sample_size]

        question = self.db.get(Question, question_id)
        question_context = self._build_question_context(question)

        event_reviews: List[EventReviewResult] = []
        approved_count = 0
        rejected_count = 0

        total_events = len(events)
        for idx, event in enumerate(events, 1):
            # Auto-approve outcome events (automatically generated Yes/No outcomes)
            if event.is_outcome:
                logger.info(
                    f"[{idx}/{total_events}] Auto-approving outcome event: {event.id}"
                )
                event.review_status = ReviewStatus.APPROVED
                event.review_note = "Auto-approved (outcome event)"
                event.updated_at = datetime.now(timezone.utc)
                self.db.save(Event, event)
                approved_count += 1
                continue

            logger.info(f"[{idx}/{total_events}] Reviewing event: {event.id}")
            review = await self._review_single_event(event, question_context)
            event_reviews.append(review)

            if review.approved:
                approved_count += 1
                event.review_status = ReviewStatus.APPROVED
            else:
                rejected_count += 1
                event.review_status = ReviewStatus.REJECTED

            event.review_note = f"LLM Review: {review.reasoning}"
            event.updated_at = datetime.now(timezone.utc)
            self.db.save(Event, event)

        criteria_met = self._check_criteria(events, event_reviews)

        overall_assessment = self._build_assessment(
            question_id, events, event_reviews, criteria_met
        )

        return EventReviewReport(
            question_id=question_id,
            total_events=len(events),
            approved_events=approved_count,
            rejected_events=rejected_count,
            pending_events=len(events) - approved_count - rejected_count,
            event_reviews=event_reviews,
            overall_assessment=overall_assessment,
            meets_criteria=all(criteria_met.values()),
            criteria_met=criteria_met,
            reviewed_at=datetime.now(timezone.utc),
        )

    async def review_pending_events(
        self,
        db_path: Optional[str] = None,
        sample_size: Optional[int] = None,
        seed: Optional[int] = None,
        skip_criteria: bool = False,
    ) -> List[EventReviewReport]:
        """Review all pending events in the database.

        Args:
            db_path: Optional custom database path
            sample_size: Optional limit on questions to review
            seed: Optional random seed for sampling
            skip_criteria: If True, review all questions regardless of criteria

        Returns:
            List of EventReviewReport for each question reviewed
        """
        db = self.get_db(db_path)

        pending_events = db.get_many(Event, filters={"review_status": "pending"})

        question_ids = list(set(e.extracted_for_question_id for e in pending_events))

        if not skip_criteria:
            filtered_ids = []
            skipped = 0
            for qid in question_ids:
                if self._question_meets_criteria_fast(qid):
                    filtered_ids.append(qid)
                else:
                    skipped += 1
                    logger.info(f"Skipping {qid}: does not meet criteria")
            if skipped > 0:
                console.print(
                    f"[yellow]Skipped {skipped} questions that don't meet criteria[/yellow]"
                )
            question_ids = filtered_ids

        if not question_ids:
            logger.warning("No questions meet criteria for review")
            return []

        if seed is not None:
            import random

            random.seed(seed)
            random.shuffle(question_ids)

        if sample_size and sample_size < len(question_ids):
            question_ids = question_ids[:sample_size]

        reports: List[EventReviewReport] = []
        for qid in question_ids:
            logger.info(f"Reviewing events for question: {qid}")
            report = await self.review_events_for_question(qid)
            reports.append(report)

        return reports

    async def _review_single_event(
        self, event: Event, question_context: str
    ) -> EventReviewResult:
        """Review a single event using LLM.

        Args:
            event: The event to review
            question_context: Context about the question

        Returns:
            EventReviewResult with LLM's assessment
        """
        articles = self._get_event_articles(event)
        article_context = self._build_article_context(articles)

        prompt = self._build_review_prompt(event, question_context, article_context)

        messages = [
            {
                "role": "system",
                "content": "You are an expert fact-checker and event verification specialist. "
                "Your task is to review events extracted from articles for accuracy and relevance. "
                "Be strict but fair - approve events that are supported by evidence and have reasonable dates. "
                "Reject events that are hallucinated, have incorrect dates. "
                "IMPORTANT: Your response must be valid JSON only, with no additional text.",
            },
            {"role": "user", "content": prompt},
        ]

        response = None
        try:
            response = await self.llm_client.acomplete(
                messages=messages,
                response_format={"type": "json_object"},
            )
            result = json.loads(response)
        except json.JSONDecodeError:
            import re

            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if json_match:
                try:
                    result = json.loads(json_match.group())
                except Exception as e2:
                    logger.error(f"LLM review failed for event {event.id}: {e2}")
                    return EventReviewResult(
                        event_id=event.id,
                        approved=False,
                        confidence=0.0,
                        issues=[f"LLM returned invalid JSON: {str(e2)}"],
                        reasoning="Review could not be completed due to LLM error",
                        suggested_status="pending",
                    )
            else:
                logger.error(f"LLM review failed for event {event.id}: No JSON found")
                return EventReviewResult(
                    event_id=event.id,
                    approved=False,
                    confidence=0.0,
                    issues=[f"LLM did not return JSON: {response[:100]}"],
                    reasoning="Review could not be completed due to LLM error",
                    suggested_status="pending",
                )
        except Exception as e:
            logger.error(f"LLM review failed for event {event.id}: {e}")
            return EventReviewResult(
                event_id=event.id,
                approved=False,
                confidence=0.0,
                issues=[f"LLM review failed: {str(e)}"],
                reasoning="Review could not be completed due to LLM error",
                suggested_status="pending",
            )

        return EventReviewResult(
            event_id=event.id,
            approved=result.get("approved", False),
            confidence=result.get("confidence", 0.5),
            issues=result.get("issues", []),
            reasoning=result.get("reasoning", ""),
            suggested_status=result.get("suggested_status", "pending"),
        )

    def _build_question_context(self, question: Optional[Question]) -> str:
        """Build context string from question."""
        if not question:
            return "No question context available"

        return f"""Question: {question.question_text}
Resolution: {question.ground_truth}
Resolution Date: {question.resolution_date}
Domain: {question.domain}
Source: {question.source}"""

    def _get_event_articles(self, event: Event) -> List[Article]:
        """Get articles related to an event."""
        if not event.article_ids:
            return []

        articles = []
        for article_id in event.article_ids[:5]:
            article = self.db.get(Article, article_id)
            if article:
                articles.append(article)
        return articles

    def _build_article_context(self, articles: List[Article]) -> str:
        """Build context from related articles."""
        if not articles:
            return "No source articles available"

        context_parts = []
        for i, article in enumerate(articles, 1):
            content = article.content or ""
            context_parts.append(
                f"Article {i} ({article.url or article.id}):\n"
                f"Title: {article.title}\n"
                f"Published: {article.published_date}\n"
                f"Content: {content[:2000] if content else 'N/A'}..."
            )
        return "\n\n".join(context_parts)

    def _build_review_prompt(
        self, event: Event, question_context: str, article_context: str
    ) -> str:
        """Build the LLM review prompt."""
        return f"""Review the following event for accuracy and relevance.

## Source Articles
{article_context}

## Event to Review
- ID: {event.id}
- Title: {event.title}
- Description: {event.description}
- Type: {event.event_type}
- Status: {event.status}
- Occurred Date: {event.occurred_date}
- Predicted Date: {event.predicted_date}
- Is Outcome: {event.is_outcome}

## Review Guidelines
IGNORE the question context - it is only provided for reference. The question text should NOT impact your decision.

Focus ONLY on whether the event is FACTUALLY ACCURATE based on the source articles:

1. **Factual accuracy** - APPROVE if:
   - The article title OR content mentions the key elements of the event
   - The event is factually correct based on the source
   
   REJECT only if:
   - The article explicitly contradicts the event (e.g., article says "Team A wins" but event claims "Team B wins")
   - Key facts in the event are clearly wrong
   - The occurred date is clearly wrong (not just slightly off)

2. **Content issues** - If article content is truncated/HTML/navigation only:
   - Check if article TITLE supports the event
   - Check if occurred_date matches publication date
   - If title supports and date matches, lean toward APPROVE

3. **Temporal validity** - If dates are close (within days), that's good enough

IMPORTANT: 
- Question relevance should NOT affect approval
- When in doubt, APPROVE - it's better to keep plausible events than reject valid ones
- The question just provides context about what topic we're studying, not a filter for events

## Output Format
Provide your review as JSON:
{{
    "approved": true/false,
    "confidence": 0.0-1.0,
    "issues": ["issue1", "issue2"],
    "reasoning": "Your detailed reasoning",
    "suggested_status": "approved/rejected/pending"
}}
"""

    def _check_criteria(
        self, events: List[Event], reviews: List[EventReviewResult]
    ) -> Dict[str, bool]:
        """Check if events meet the review criteria."""
        approved = [r for r in reviews if r.approved]

        has_enough_events = len(approved) >= self.criteria.min_events
        has_time_coverage = self._check_time_coverage(events)
        has_depth = self._check_causal_depth(events)

        return {
            "min_events": has_enough_events,
            "time_coverage": has_time_coverage
            if self.criteria.require_time_coverage
            else True,
            "min_depth": has_depth if self.criteria.check_factual_accuracy else True,
        }

    def _check_time_coverage(self, events: List[Event]) -> bool:
        """Check if events span a reasonable time range."""
        dates = [e.occurred_date for e in events if e.occurred_date]
        if len(dates) < 2:
            return False
        return True

    def _check_causal_depth(self, events: List[Event]) -> bool:
        """Check if events have sufficient causal depth."""

        max_depth = 0
        for event in events:
            depth = self._calculate_depth(event, set())
            max_depth = max(max_depth, depth)

        return max_depth >= self.criteria.min_depth

    def _question_meets_criteria_fast(self, question_id: str) -> bool:
        """Quickly check if a question meets criteria without LLM review.

        This is a fast check that doesn't require LLM calls.
        For initial review, we check TOTAL events (not approved).
        """
        events = self.db.get_many(
            Event, filters={"extracted_for_question_id": question_id}
        )

        if not events:
            return False

        if len(events) < self.criteria.min_events:
            return False

        if self.criteria.require_time_coverage:
            dates = [e.occurred_date for e in events if e.occurred_date]
            if len(dates) < 2:
                return False

        if self.criteria.check_factual_accuracy:
            max_depth = 0
            for event in events:
                depth = self._calculate_depth(event, set())
                max_depth = max(max_depth, depth)
            if max_depth < self.criteria.min_depth:
                return False

        return True

    def _calculate_depth(self, event: Event, visited: set) -> int:
        """Calculate the depth of causal chain starting from an event."""
        if event.id in visited:
            return 0
        visited.add(event.id)

        incoming = self.db.get_many(
            CausalHypothesis, filters={"target_event_id": event.id}
        )
        if not incoming:
            return 1

        return 1 + max(
            self._calculate_depth(self.db.get(Event, h.source_event_id), visited.copy())
            for h in incoming
            if self.db.get(Event, h.source_event_id)
        )

    def _build_assessment(
        self,
        question_id: str,
        events: List[Event],
        reviews: List[EventReviewResult],
        criteria_met: Dict[str, bool],
    ) -> str:
        """Build overall assessment string."""
        approved = sum(1 for r in reviews if r.approved)
        total = len(events)

        assessment = f"Reviewed {total} events for {question_id}: "
        assessment += f"{approved} approved, {total - approved} rejected. "

        unmet = [k for k, v in criteria_met.items() if not v]
        if unmet:
            assessment += f"Criteria not met: {', '.join(unmet)}."
        else:
            assessment += "All criteria met."

        return assessment
