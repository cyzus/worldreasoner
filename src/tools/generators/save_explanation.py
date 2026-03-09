"""Tool to save a natural language causal explanation to a question."""

from typing import Optional

from smolagents import Tool
from src.domain.models import Question
from src.tools.base.base import ToolResponseMixin
from src.tools.base.schema_helper import pydantic_to_output_schema
from src.tools.base.output_models import SaveExplanationOutput
from src.utils.logging import logger


class SaveExplanationTool(Tool, ToolResponseMixin):
    """Tool to save a natural language causal explanation for a question.

    This is used by the HindsightAgent to store its explanation so the
    GraphBuilderAgent can later convert it into a structured graph.
    """

    name = "save_explanation"
    description = """Save the detailed natural language causal explanation for the question.
    
    Use this tool once you have collected all evidence and formulated a complete
    explanation of how the outcome occurred. The explanation should follow the
    required format with dated events, citations [art_id], and explicit causal language.
    """

    inputs = {
        "explanation": {
            "type": "string",
            "description": "The full natural language causal narrative",
        }
    }
    output_type = "object"
    output_schema = pydantic_to_output_schema(SaveExplanationOutput)

    def __init__(self, db_path: str = None, question_id: Optional[str] = None):
        """Initialize the tool.

        Args:
            db_path: Optional database path
            question_id: The ID of the question being answered
        """
        super().__init__()
        self.question_id = question_id
        from src.core.database import GenericDatabase

        self.db = GenericDatabase(db_path) if db_path else None

    def forward(self, explanation: str) -> str:
        """Save the explanation.

        Returns:
            JSON confirmation string
        """
        if not self.db:
            return SaveExplanationOutput(
                status="error",
                question_id=self.question_id or "unknown",
                message="Database is not initialized.",
            )

        if not self.question_id:
            return SaveExplanationOutput(
                status="error",
                question_id="unknown",
                message="Question ID is missing from tool context.",
            )

        question = self.db.get(Question, self.question_id)
        if not question:
            return SaveExplanationOutput(
                status="error",
                question_id=self.question_id,
                message=f"Question '{self.question_id}' not found.",
            )

        # Update question fields
        question.causal_explanation = explanation
        question.graph_built = False

        # Save back to db
        self.db.save(Question, question)
        logger.info(f"Saved causal explanation for question {self.question_id}")

        return SaveExplanationOutput(
            status="success",
            question_id=self.question_id,
            message="Explanation successfully saved. The graph builder will process it next.",
        )
