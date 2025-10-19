"""Question generation stage for Question Pipeline."""

import json
from typing import List, Optional
from pydantic import BaseModel

from ..base import PipelineStage
from ...models import Event, Question, Article
from ...config import QuestionConfig
from src.agents.base import BaseAgent
from src.utils.config import get_config
from .tools import QuestionGeneratorTool, EventDetailsTool
from ..prompts import QuestionGenerationPrompts


class QuestionGenerationStage(PipelineStage[Event, Question]):
    """Generates forecast questions from events using LLM-powered agent.
    
    Uses agentic approach to create high-quality forecast questions.
    The agent can optionally request full event details and article content
    for deeper context when generating questions.
    """
    
    def __init__(self, config: QuestionConfig, articles: Optional[List[Article]] = None):
        super().__init__(name="QuestionGeneration", config=config)
        # Store articles for EventDetailsTool
        self.articles = articles or []
        # Tools will be initialized in process() when we have events
        self.question_tool = QuestionGeneratorTool()
        self.event_details_tool = None  # Will be created when we have events
        self.base_agent = None  # Will be created in process()
    
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
            from datetime import datetime, timezone
            current_date = datetime.now(timezone.utc)
            
            # Create EventDetailsTool with events and articles
            self.event_details_tool = EventDetailsTool(
                events=inputs,
                articles=self.articles
            )
            
            # Create agent with both tools
            app_config = get_config()
            self.base_agent = BaseAgent(
                config=app_config,
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
            print(f"Agent response: {result[:200] if isinstance(result, str) else result}")
            
            # Get generated questions from the tool's internal storage
            questions = self.question_tool.generated_questions
            
            # Apply max_questions limit from config if set
            if self.config.max_questions:
                questions = questions[:self.config.max_questions]
            
            return questions
            
        except Exception as e:
            print(f"Error generating questions: {e}")
            return []
