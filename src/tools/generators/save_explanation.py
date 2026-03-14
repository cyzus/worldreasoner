"""Tool to save a natural language causal explanation to a question."""

import re
from typing import List, Optional

from smolagents import Tool
from src.domain.models import Question
from src.tools.base.base import ToolResponseMixin
from src.tools.base.schema_helper import pydantic_to_output_schema
from src.tools.base.output_models import SaveExplanationOutput
from src.utils.logging import logger

_ARTICLE_ID_PATTERN = re.compile(r"\bart_[a-z0-9_]{5,}\b")
_MIN_LENGTH = 300
_MARKDOWN_HEADING_PATTERN = re.compile(r"(?m)^\s{0,3}#{2,6}\s+(.+?)\s*$")

# Required markdown sections for a graph-ready hindsight report.
_REQUIRED_SECTION_ALIASES = {
    "executive_summary": ["executive summary"],
    "timeline": ["timeline of key events", "timeline"],
    "causal_chain": ["causal chain analysis", "causal chain"],
    "countervailing": ["countervailing factors", "counterfactual factors"],
    "event_inventory": ["event candidate inventory", "event candidates"],
    "evidence_table": ["evidence mapping table", "evidence table"],
    "uncertainties": [
        "uncertainties and alternative paths",
        "uncertainties",
        "alternative paths",
    ],
}


def _extract_markdown_headings(text: str) -> List[str]:
    """Extract normalized markdown headings (h2-h6)."""
    return [h.strip().lower() for h in _MARKDOWN_HEADING_PATTERN.findall(text)]


def _has_required_section(headings: List[str], aliases: List[str]) -> bool:
    """Check if any alias appears in extracted markdown headings."""
    return any(alias in headings for alias in aliases)


def _has_markdown_table(text: str) -> bool:
    """Lightweight markdown table check: header row plus separator row."""
    has_header = bool(re.search(r"(?m)^\s*\|.+\|\s*$", text))
    has_separator = bool(re.search(r"(?m)^\s*\|?\s*[-:]{3,}\s*(\|\s*[-:]{3,}\s*)+\|?\s*$", text))
    return has_header and has_separator


def _validate_explanation(explanation: str):
    """Return (warnings, article_ref_count) for the given explanation."""
    warnings: List[str] = []
    if len(explanation.strip()) < _MIN_LENGTH:
        warnings.append(
            f"Explanation is very short ({len(explanation.strip())} chars). "
            "Add more detail about the causal chain."
        )
    refs = _ARTICLE_ID_PATTERN.findall(explanation)
    if not refs:
        warnings.append(
            "No article ID references found (expected patterns like art_tech_20240101_001_abc). "
            "Call get_question_articles and cite sources inline."
        )
    causal_markers = ["caused", "triggered", "led to", "resulted in", "because", "therefore", "consequently"]
    if not any(m in explanation.lower() for m in causal_markers):
        warnings.append(
            "No explicit causal language detected. Use words like 'caused', 'triggered', "
            "'led to', 'resulted in' to connect events."
        )

    headings = _extract_markdown_headings(explanation)
    missing_sections = []
    for section_key, aliases in _REQUIRED_SECTION_ALIASES.items():
        if not _has_required_section(headings, aliases):
            missing_sections.append(section_key)

    if missing_sections:
        pretty = ", ".join(missing_sections)
        warnings.append(
            "Missing required markdown sections for structured causal report: "
            f"{pretty}. Use markdown headings exactly as requested in the prompt."
        )

    # Evidence section is expected to include a markdown table for claim-to-source traceability.
    if _has_required_section(headings, _REQUIRED_SECTION_ALIASES["evidence_table"]):
        if not _has_markdown_table(explanation):
            warnings.append(
                "Evidence Mapping Table section found, but no valid markdown table detected. "
                "Add a table with header and separator rows."
            )

    return warnings, len(set(refs))


class SaveExplanationTool(Tool, ToolResponseMixin):
    """Tool to save a natural language causal explanation for a question.

    This is used by the HindsightAgent to store its explanation so the
    GraphBuilderAgent can later convert it into a structured graph.
    """

    name = "save_explanation"
    description = """Save the natural language causal explanation for the question.

    Call this once you have written a complete narrative explaining how and why the outcome
    occurred. The explanation should cite sources using exact article IDs and use explicit
    causal language. Returns validation warnings if the explanation is weak — address them
    and call save_explanation again before finishing.
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

    def forward(self, explanation: str) -> SaveExplanationOutput:
        """Save the explanation with validation.

        Returns:
            SaveExplanationOutput with status, warnings, and article reference count.
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

        warnings, ref_count = _validate_explanation(explanation)

        # Update question fields
        question.causal_explanation = explanation
        question.graph_built = False

        # Save back to db
        self.db.save(Question, question)
        logger.info(
            f"Saved causal explanation for question {self.question_id} "
            f"({ref_count} article refs, {len(warnings)} warnings)"
        )

        if warnings:
            logger.warning(
                f"Explanation for {self.question_id} has quality warnings: {warnings}"
            )
            return SaveExplanationOutput(
                status="saved_with_warnings",
                question_id=self.question_id,
                message=(
                    "Explanation saved, but quality warnings were detected. "
                    "Review the warnings and consider improving the explanation before finishing."
                ),
                article_references_found=ref_count,
                warnings=warnings,
            )

        return SaveExplanationOutput(
            status="success",
            question_id=self.question_id,
            message="Explanation saved. The graph builder will process it next.",
            article_references_found=ref_count,
        )
