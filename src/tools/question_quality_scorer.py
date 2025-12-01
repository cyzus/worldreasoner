"""Tool for scoring the quality of forecast questions using an LLM."""

import json
from typing import List, Dict, Any, Optional

from pydantic import BaseModel, Field
from smolagents.tools import Tool
from src.core.collectors import ResultCollector
from src.domain.models.question import Question
from src.llm import LiteLLMClient
from src.config import get_config
from src.pipelines.prompts.question_quality import QUESTION_QUALITY_ASSESSMENT_PROMPT, QUALITY_ASSESSMENT_SCHEMA


class QualityAssessment(BaseModel):
    """Structured output for a single question's quality assessment."""
    question_id: str
    composite_score: float = Field(..., ge=0.0, le=1.0)
    dimensions: Dict[str, float]
    reasoning: str


class QuestionQualityScorer(Tool):
    """
    A tool that uses an LLM to assess the quality of a batch of forecast questions.
    It returns a structured JSON object with scores for multiple quality dimensions.
    """
    name: str = "QuestionQualityScorer"
    description: str = "Assess a batch of forecast questions for quality based on multiple dimensions."
    inputs: dict = {
        "questions": {
            "type": "array",
            "description": "A list of Question objects to be assessed.",
            "items": {
                "type": "object"
            }
        }
    }
    output_type: str = "string"  # JSON string

    def __init__(
        self,
        collector: Optional[ResultCollector[QualityAssessment]] = None,
    ):
        super().__init__()
        self.collector = collector
        app_config = get_config()
        self.llm_client = LiteLLMClient(app_config.llm)

    def _prepare_question_json(self, questions: List[Question]) -> str:
        """Prepare a JSON string of questions for the prompt."""
        question_list = []
        for q in questions:
            # Create a simplified dict for the prompt
            question_data = {
                "id": q.id,
                "question_text": q.question_text,
                "question_type": q.question_type.value,
                "domain": q.domain.value,
                "difficulty": q.difficulty,
                "resolution_date": q.resolution_date.isoformat(),
                "context": q.context,
                "resolution_criteria": q.resolution_criteria,
                "options": q.options,
            }
            question_list.append(question_data)
        return json.dumps(question_list, indent=2)

    async def forward(self, questions: List[Question]) -> str:
        """
        Assess the quality of the questions and return the assessment as a JSON string.
        
        Args:
            questions: A list of Question objects to assess.
            
        Returns:
            A JSON string containing the quality assessments for each question.
        """
        if not questions:
            return json.dumps({"assessments": []})

        questions_json = self._prepare_question_json(questions)

        prompt = QUESTION_QUALITY_ASSESSMENT_PROMPT.format(
            num_questions=len(questions),
            questions_json=questions_json
        )
        
        # Create messages for the LLM
        messages = [{"role": "user", "content": prompt}]

        # Call the LLM with structured output
        response_str = await self.llm_client.acomplete(messages=messages)
        
        # LiteLLM with some providers returns a string that needs to be parsed
        try:
            response_json = json.loads(response_str)
        except json.JSONDecodeError:
            # Handle cases where the response is not valid JSON
            # This might happen if the model doesn't respect the JSON output format constraint
            # You could try to extract JSON from the string or log an error
            return json.dumps({"error": "Invalid JSON response from LLM", "response": response_str})

        # Assuming response_json is a dict
        assessments_data = response_json.get("assessments", [])

        # Parse and collect results
        parsed_assessments = []
        for data in assessments_data:
            assessment = QualityAssessment(**data)
            parsed_assessments.append(assessment)
            if self.collector is not None:
                self.collector.add(assessment)

        # Return the raw JSON string as per tool's output_type
        return json.dumps(response_json)
