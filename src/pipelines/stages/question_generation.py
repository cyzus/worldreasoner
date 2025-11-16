"""Question generation stage for Question Pipeline."""

import json
from typing import List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel

from ..base import PipelineStage
from src.domain.models import Event, Question, Article
from src.config.pipeline import QuestionPipelineConfig
from src.agents.factory import AgentFactory
from .tools import QuestionGeneratorTool, EventDetailsTool, ArticleRetrievalTool
from .collectors import ResultCollector
from ..prompts import QuestionGenerationPrompts
from src.utils.logging import logger
from src.utils.usage_tracking import UsageTracker, log_usage


class QuestionGenerationStage(PipelineStage[Event, Question]):
    """Generates forecast questions from events using LLM-powered agent.
    
    Uses agentic approach to create high-quality forecast questions.
    The agent can optionally request full event details and article content
    for deeper context when generating questions.
    """
    
    def __init__(self, config: QuestionPipelineConfig, db_path: Optional[str] = None):
        super().__init__(name="QuestionGeneration", config=config)

        # Store db_path for tools
        self.db_path = db_path

        # Create result collector for questions
        self.collector = ResultCollector[Question]()

        # Create question tool with collector
        self.question_tool = QuestionGeneratorTool(collector=self.collector, require_ground_truth=config.require_ground_truth)

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
        
        try:
            # Get current date for context
            current_date = datetime.now(timezone.utc)

            filtered_events = inputs
            # Create tools with database access
            self.event_details_tool = EventDetailsTool(db_path=self.db_path)
            self.article_retrieval_tool = ArticleRetrievalTool(db_path=self.db_path)

            # Create agent using factory
            self.base_agent = AgentFactory.create_base_agent(
                tools=[self.event_details_tool, self.question_tool, self.article_retrieval_tool]
            )

            # Determine max questions
            max_questions = self.config.max_questions or 10

            # Get instruction from prompts module
            instruction = self.prompts.get_instruction(
                current_date=current_date,
                events=filtered_events,  # Use filtered events
                max_questions=max_questions,
                domains=self.config.domains,
                require_ground_truth=self.config.require_ground_truth
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
            
            # Apply max_questions limit from config if set
            if self.config.max_questions:
                questions = questions[:self.config.max_questions]

            # Log usage summary for this stage
            if self.usage_tracker.total_calls > 0:
                self.usage_tracker.log_summary(context="QuestionGeneration")

            return questions
            
        except Exception as e:
            logger.error(f"Error generating questions: {e}")
            return []
