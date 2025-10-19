"""Question generation stage for Question Pipeline."""

import json
from typing import List
from pydantic import BaseModel

from ..base import PipelineStage
from ...models import Event, Question
from ...config import QuestionConfig
from src.agents.base import BaseAgent
from src.utils.config import get_config
from .tools import QuestionGeneratorTool
from ..prompts import QuestionGenerationPrompts


class QuestionGenerationStage(PipelineStage[Event, Question]):
    """Generates forecast questions from events using LLM-powered agent.
    
    Uses agentic approach to create high-quality forecast questions.
    """
    
    def __init__(self, config: QuestionConfig):
        super().__init__(name="QuestionGeneration", config=config)
        # Create BaseAgent with QuestionGeneratorTool
        app_config = get_config()
        self.question_tool = QuestionGeneratorTool()  # Keep reference to tool
        self.base_agent = BaseAgent(config=app_config, tools=[self.question_tool])
    
    async def process(self, inputs: List[Event]) -> List[Question]:
        """Generate forecast questions from events using LLM agent.
        
        Args:
            inputs: List of events to generate questions about
            
        Returns:
            List of generated questions
        """
        if not inputs:
            return []
        
        if not inputs:
            return []
        
        try:
            # Get current date for context
            from datetime import datetime, timezone
            current_date = datetime.now(timezone.utc)
            
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
