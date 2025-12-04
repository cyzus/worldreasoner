"""Question generation stage for Question Pipeline."""

import json
from typing import List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel

from ..base import PipelineStage
from src.domain.models import Event, Question, Article
from src.config.pipeline import QuestionPipelineConfig
from src.agents.factory import AgentFactory
from src.tools import QuestionGeneratorTool, BatchQuestionGeneratorTool, EventDetailsTool, ArticleRetrievalTool, BatchArticleRetrievalTool
from src.core.collectors import ResultCollector
from ..prompts import QuestionGenerationPrompts
from src.utils.logging import logger
from src.utils.usage_tracking import UsageTracker, log_usage


class QuestionGenerationStage(PipelineStage[Event, Question]):
    """Generates forecast questions from events using LLM-powered agent.
    
    Uses agentic approach to create high-quality forecast questions.
    The agent can optionally request full event details and article content
    for deeper context when generating questions.
    """
    
    def __init__(self, config: QuestionPipelineConfig, db_path: Optional[str] = None,
                 type_hints: Optional[List[str]] = None, category_hints: Optional[List[str]] = None,
                 existing_question_ids: Optional[set] = None, target_count: Optional[int] = None):
        super().__init__(name="QuestionGeneration", config=config)

        # Store db_path for tools
        self.db_path = db_path

        # Store hints for intelligent generation
        self.type_hints = type_hints  # Priority types needed
        self.category_hints = category_hints  # Priority categories needed
        self.existing_question_ids = existing_question_ids or set()  # For deduplication
        self.target_count = target_count  # Override config.max_questions if provided

        # Create result collector for questions
        self.collector = ResultCollector[Question]()

        # Create batch question tool with collector and existing IDs for early filtering
        self.question_tool = BatchQuestionGeneratorTool(
            collector=self.collector,
            require_ground_truth=config.require_ground_truth,
            existing_question_ids=self.existing_question_ids
        )

        # Prompt generator
        self.prompts = QuestionGenerationPrompts()

        self.event_details_tool = None
        self.article_retrieval_tool = None

        self.base_agent = None

        # Usage tracking
        self.usage_tracker = UsageTracker()
        
    async def process(self, inputs: List[Event]) -> List[Question]:
        """Generate forecast questions from events using LLM agent.

        The agent has access to:
        - Event summaries (truncated descriptions)
        - EventDetailsTool to request full event + article content
        - QuestionGeneratorTool to store generated questions

        Args:
            inputs: List of events to generate questions about

        Returns:
            List of generated questions
        """
        if not inputs:
            return []

        # Early exit if we already have enough questions (batching optimization)
        # The collector is shared across batches, so check how many we've collected so far
        # Use target_count if provided (from orchestrator), otherwise fall back to config
        max_questions = self.target_count if self.target_count is not None else (self.config.max_questions or 10)
        current_count = len(self.collector.get_all())

        if current_count >= max_questions:
            logger.info(f"Already collected {current_count}/{max_questions} questions, skipping batch")
            return []

        # Adjust target for this batch based on how many we still need
        remaining_needed = max_questions - current_count
        logger.debug(f"Current: {current_count}, Target: {max_questions}, This batch will aim for: {remaining_needed}")

        try:
            # Get current date for context
            current_date = datetime.now(timezone.utc)

            # Determine target domains
            # Use category_hints as domains if provided (focus on missing categories)
            # Otherwise fall back to config domains
            target_domains = self.category_hints if self.category_hints else self.config.domains

            # Filter events by domain if target_domains is specified
            if target_domains:
                filtered_events = [
                    event for event in inputs
                    if event.domain.value in target_domains
                ]
                logger.info(f"Filtered {len(inputs)} events to {len(filtered_events)} events matching domains: {target_domains}")
            else:
                filtered_events = inputs
                logger.info(f"No domain filter applied, using all {len(inputs)} events")

            # Apply batch size limit with domain distribution
            batch_size = self.config.event_batch_size
            if len(filtered_events) > batch_size:
                # Distribute events evenly across domains for better question diversity
                from collections import defaultdict
                events_by_domain = defaultdict(list)
                for event in filtered_events:
                    events_by_domain[event.domain.value].append(event)

                # Calculate events per domain for balanced distribution
                num_domains = len(events_by_domain)
                events_per_domain = batch_size // num_domains
                remainder = batch_size % num_domains

                # Select events from each domain
                distributed_events = []
                for domain, events in sorted(events_by_domain.items()):
                    # Take events_per_domain from this domain (+ 1 if remainder)
                    take = events_per_domain + (1 if remainder > 0 else 0)
                    distributed_events.extend(events[:take])
                    if remainder > 0:
                        remainder -= 1

                logger.info(f"Distributed {batch_size} events across {num_domains} domains: " +
                           f"{', '.join(f'{d}:{len([e for e in distributed_events if e.domain.value == d])}' for d in events_by_domain.keys())}")
                filtered_events = distributed_events
            else:
                logger.info(f"Using all {len(filtered_events)} filtered events (within batch size {batch_size})")

            if not filtered_events:
                logger.warning("No events remain after filtering")
                return []

            # Create tools with database access
            self.event_details_tool = EventDetailsTool(db_path=self.db_path)
            self.article_retrieval_tool = BatchArticleRetrievalTool(db_path=self.db_path)

            # Create agent using factory
            self.base_agent = AgentFactory.create_base_agent(
                tools=[self.event_details_tool, self.question_tool, self.article_retrieval_tool]
            )

            # Get instruction from prompts module
            # Use remaining_needed (already calculated above) to tell agent how many questions to generate
            instruction = self.prompts.get_instruction(
                current_date=current_date,
                events=filtered_events,  # Use filtered events
                max_questions=remaining_needed,  # Use adjusted target based on what we still need
                domains=target_domains,
                require_ground_truth=self.config.require_ground_truth,
                type_hints=self.type_hints,
                category_hints=self.category_hints
            )
            
            # Run the agent with the instruction
            result = self.base_agent.run(instruction)

            # Track token usage
            usage_metrics = self.base_agent.get_last_usage()
            if usage_metrics:
                self.usage_tracker.add_usage(usage_metrics)
                log_usage(usage_metrics, context="QuestionGeneration")

            # Agent's response is just a summary for logging
            logger.debug(f"Agent response for question generation: {result[:200] if isinstance(result, str) else result}")

            # Get generated questions from the collector
            questions = self.collector.get_all()

            # Log usage summary for this stage
            if self.usage_tracker.total_calls > 0:
                self.usage_tracker.log_summary(context="QuestionGeneration")

            return questions
            
        except Exception as e:
            logger.error(f"Error generating questions: {e}")
            return []
