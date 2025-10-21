"""Question generation stage for Question Pipeline."""

import json
from typing import List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel

from ..base import PipelineStage
from src.domain.models import Event, Question, Article
from src.config.pipeline import QuestionPipelineConfig
from src.agents.factory import AgentFactory
from .tools import QuestionGeneratorTool, EventDetailsTool
from .collectors import ResultCollector
from ..prompts import QuestionGenerationPrompts
from src.utils.logging import logger


class QuestionGenerationStage(PipelineStage[Event, Question]):
    """Generates forecast questions from events using LLM-powered agent.
    
    Uses agentic approach to create high-quality forecast questions.
    The agent can optionally request full event details and article content
    for deeper context when generating questions.
    """
    
    def __init__(self, config: QuestionPipelineConfig, articles: Optional[List[Article]] = None):
        super().__init__(name="QuestionGeneration", config=config)
        
        # Store articles for EventDetailsTool
        self.articles = articles or []
        
        # Create result collector for questions
        self.collector = ResultCollector[Question]()
        
        # Create question tool with collector
        self.question_tool = QuestionGeneratorTool(collector=self.collector)
        
        # EventDetailsTool and agent will be initialized in process() when we have events
        self.event_details_tool = None
        self.base_agent = None
    
    def set_articles(self, articles: List[Article]):
        """Set articles for the EventDetailsTool.
        
        Args:
            articles: List of articles to make available to the agent
        """
        self.articles = articles
    
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
            
            # Create EventDetailsTool with events and articles
            self.event_details_tool = EventDetailsTool(
                events=inputs,
                articles=self.articles
            )
            
            # Create agent using factory
            self.base_agent = AgentFactory.create_base_agent(
                tools=[self.event_details_tool, self.question_tool]
            )
            
            # Determine max questions
            max_questions = self.config.max_questions or 10
            
            # Get instruction from prompts module
            instruction = QuestionGenerationPrompts.get_generation_instruction(
                current_date=current_date,
                events=inputs,
                max_questions=max_questions,
                domains=self.config.domains
            )
            
            # Run the agent with the instruction
            result = self.base_agent.run(instruction)
            
            # Agent's response is just a summary for logging
            logger.debug(f"Agent response for question generation: {result[:200] if isinstance(result, str) else result}")
            
            # Get generated questions from the collector
            questions = self.collector.get_all()
            
            # Apply max_questions limit from config if set
            if self.config.max_questions:
                questions = questions[:self.config.max_questions]
            
            return questions
            
        except Exception as e:
            logger.error(f"Error generating questions: {e}")
            return []
