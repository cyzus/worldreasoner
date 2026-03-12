"""Tool for scoring the quality of forecast questions using an LLM."""

import json
from typing import List, Dict, Optional

from pydantic import BaseModel, Field
from smolagents.tools import Tool
from src.core.collectors import ResultCollector
from src.domain.models.question import Question
from src.core.llm import LiteLLMClient
from src.config import get_config
from src.pipelines.prompts.question_quality import (
    QUESTION_QUALITY_ASSESSMENT_PROMPT,
)
from src.utils.logging import logger
from src.tools.base.schema_helper import pydantic_to_output_schema
from src.tools.base.output_models import QuestionQualityOutput


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
    description: str = (
        "Assess a batch of forecast questions for quality based on multiple dimensions."
    )
    inputs: dict = {
        "questions": {
            "type": "array",
            "description": "A list of Question objects to be assessed.",
            "items": {"type": "object"},
        }
    }
    output_type: str = "object"
    output_schema = pydantic_to_output_schema(QuestionQualityOutput)

    def __init__(
        self,
        collector: Optional[ResultCollector[QualityAssessment]] = None,
        timeout: Optional[int] = None,
        dimension_weights: Optional[Dict[str, float]] = None,
    ):
        super().__init__()
        self.collector = collector

        app_config = get_config()

        # Use provided weights, or fall back to config defaults
        if dimension_weights is not None:
            self.dimension_weights = dimension_weights
        else:
            # Get default weights from config
            from src.config.pipeline import QuestionQualityConfig

            default_config = QuestionQualityConfig()
            self.dimension_weights = default_config.dimension_weights

        # Override timeout if provided
        llm_config = app_config.llm.model_copy()
        if timeout is not None:
            llm_config.timeout = timeout
        self.llm_client = LiteLLMClient(llm_config)

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

    def _calculate_weighted_score(self, dimensions: Dict[str, float]) -> float:
        """Calculate weighted composite score from dimension scores.

        Args:
            dimensions: Dictionary of dimension scores (0.0-1.0)

        Returns:
            Weighted composite score (0.0-1.0)
        """
        weighted_sum = 0.0
        for dimension, weight in self.dimension_weights.items():
            if dimension in dimensions:
                weighted_sum += dimensions[dimension] * weight
            else:
                logger.warning(
                    f"Dimension '{dimension}' missing from assessment, using 0.0"
                )
        return weighted_sum

    async def forward(self, questions: List[Question]) -> str:
        """
        Assess the quality of the questions and return the assessment as a JSON string.

        Args:
            questions: A list of Question objects to assess.

        Returns:
            A JSON string containing the quality assessments for each question.
        """
        if not questions:
            return QuestionQualityOutput(scores=[], overall_quality="unknown")

        questions_json = self._prepare_question_json(questions)

        prompt = QUESTION_QUALITY_ASSESSMENT_PROMPT.format(
            num_questions=len(questions), questions_json=questions_json
        )

        # Create messages for the LLM
        messages = [{"role": "user", "content": prompt}]

        # Call the LLM with structured JSON output
        response_str = await self.llm_client.acomplete(
            messages=messages, response_format={"type": "json_object"}
        )

        # Parse the JSON response using utility
        from src.core.llm import parse_json_response

        try:
            response_json = parse_json_response(response_str)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from LLM response: {e}")
            logger.debug(f"Raw response: {response_str[:500]}...")
            return QuestionQualityOutput(
                scores=[{"error": "Invalid JSON response from LLM", "response": response_str[:500]}],
                overall_quality="error"
            )

        # Assuming response_json is a dict
        assessments_data = response_json.get("assessments", [])

        # Parse and collect results, recalculating composite scores with weights
        parsed_assessments = []
        for data in assessments_data:
            # Recalculate composite score using weighted average instead of LLM's unweighted score
            weighted_score = self._calculate_weighted_score(data["dimensions"])
            data["composite_score"] = weighted_score

            assessment = QualityAssessment(**data)
            parsed_assessments.append(assessment)
            if self.collector is not None:
                self.collector.add(assessment)

        # Update response with recalculated scores
        assessments_list = [
            {
                "question_id": a.question_id,
                "composite_score": a.composite_score,
                "dimensions": a.dimensions,
                "reasoning": a.reasoning,
            }
            for a in parsed_assessments
        ]

        # Return QuestionQualityOutput Pydantic model
        return QuestionQualityOutput(
            scores=assessments_list,
            overall_quality=response_json.get("overall_quality", "unknown"),
        )
