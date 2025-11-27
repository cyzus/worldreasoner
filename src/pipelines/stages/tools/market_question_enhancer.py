"""Market question enhancement tool for categorizing and enriching prediction market questions."""

import json
from typing import Optional
from smolagents import Tool
from src.domain.models import Question, Domain
from src.domain.models.domain import Domain as DomainEnum


class MarketQuestionEnhancerTool(Tool):
    """Enhances prediction market questions with proper categorization and domain assignment.

    This tool helps the agent:
    1. Analyze market question text and metadata
    2. Categorize into appropriate domain
    3. Update question metadata with enriched information

    NOTE: The agent should analyze the question context and use this tool to update the domain.
    """

    name = "market_question_enhancer"
    description = """Updates a market question with improved categorization and domain assignment.

    Use this tool AFTER analyzing a market question's text, tags, and resolution criteria.
    Call this tool once for EACH question you categorize.
    """

    inputs = {
        "question_id": {"type": "string", "description": "The question ID to enhance"},
        "domain": {
            "type": "string",
            "description": f"Primary domain/category: {', '.join([d.value for d in DomainEnum])}",
            "enum": [d.value for d in DomainEnum]
        },
        "reasoning": {
            "type": "string",
            "description": "Brief explanation of why this categorization was chosen",
            "nullable": True
        }
    }
    output_type = "string"  # JSON string

    def __init__(self, questions: dict):
        """Initialize the enhancer.

        Args:
            questions: Dictionary mapping question_id -> Question object (modified in place)
        """
        super().__init__()
        self.questions = questions

    def forward(
        self,
        question_id: str,
        domain: str,
        reasoning: Optional[str] = None
    ) -> str:
        """Update question with enhanced categorization.

        Args:
            question_id: ID of question to enhance
            domain: Primary domain/category classification
            reasoning: Explanation of categorization (optional)

        Returns:
            JSON string confirming update
        """
        # Handle None reasoning
        if reasoning is None:
            reasoning = ""

        # Find question
        if question_id not in self.questions:
            return json.dumps({
                "error": f"Question ID '{question_id}' not found",
                "status": "failed"
            })

        question = self.questions[question_id]

        # Validate and set domain
        try:
            domain_enum = DomainEnum(domain)
            question.domain = domain_enum
        except ValueError:
            return json.dumps({
                "error": f"Invalid domain '{domain}'. Must be one of: {', '.join([d.value for d in DomainEnum])}",
                "status": "failed"
            })

        # Initialize metadata if it doesn't exist (Question uses extra="allow")
        if not hasattr(question, 'metadata') or question.metadata is None:
            question.metadata = {}

        # Update metadata - use domain as category
        question.metadata["category"] = domain
        question.metadata["categorization_reasoning"] = reasoning or ""

        # Return summary
        reasoning_str = reasoning or ""
        summary = {
            "question_id": question_id,
            "domain": domain,
            "reasoning": reasoning_str[:100] + "..." if len(reasoning_str) > 100 else reasoning_str,
            "status": "enhanced"
        }

        return json.dumps(summary, indent=2)
