"""Question generation tool using LLM to create forecast questions from events."""

import json
from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid

from src.domain.models import Question, QuestionType, Domain
from src.config.collection_goal import TimeHorizon
from src.utils.enums import enum_to_list
from src.utils.date_utils import parse_iso_datetime, ensure_timezone_aware
from src.tools.base.schema_helper import pydantic_to_output_schema
from src.tools.base.base import CollectorAwareTool
from src.tools.base.output_models import QuestionOutput


class QuestionGeneratorTool(CollectorAwareTool[Question]):
    """Stores and structures generated forecast questions.

    This tool helps the agent:
    1. Convert generated question text into structured Question format
    2. Generate unique question IDs
    3. Link questions to source events
    4. Set resolution criteria and dates

    NOTE: This tool does NOT generate questions itself.
    The agent should first analyze events and create forecast question text using its LLM reasoning,
    then use this tool to store each question in the proper structure.
    """

    name = "question_generator"
    description = """Stores a generated forecast question as a structured Question object. Output will be the generation status."""

    # Auto-generate inputs from Enum classes (single source of truth)
    inputs = {
        "question_text": {"type": "string", "description": "The actual question text"},
        "question_type": {
            "type": "string",
            "description": f"Question type - MUST be one of: {', '.join(enum_to_list(QuestionType))}",
            "enum": enum_to_list(QuestionType),
        },
        "domain": {
            "type": "string",
            "description": f"Question domain - one of: {', '.join(enum_to_list(Domain))}",
            "enum": enum_to_list(Domain),
        },
        "difficulty": {"type": "integer", "description": "Difficulty level 1-5"},
        "resolution_date": {
            "type": "string",
            "description": "When question can be resolved (ISO 8601 WITH timezone, e.g. 2025-12-31T23:59:59Z or 2025-12-31T23:59:59+00:00; MUST include 'Z' or an explicit offset)",
        },
        "resolution_criteria": {
            "type": "string",
            "description": "Objective rules for how to verify/resolve this question",
        },
        "related_event_ids": {
            "type": "string",
            "description": "Comma-separated event IDs",
            "nullable": True,
        },
        "related_article_ids": {
            "type": "string",
            "description": "Comma-separated article IDs that this question was generated from",
            "nullable": True,
        },
        "ground_truth": {
            "type": "string",
            "description": "Answer if already resolved",
            "nullable": True,
        },
        "resolution_reasoning": {
            "type": "string",
            "description": "Evidence/explanation for why ground_truth is what it is (only if ground_truth is provided)",
            "nullable": True,
        },
        "context": {
            "type": "string",
            "description": "Optional background information to help understand the question",
            "nullable": True,
        },
        "options": {
            "type": "string",
            "description": "For MCQ: comma-separated answer choices",
            "nullable": True,
        },
        "quantity_unit": {
            "type": "string",
            "description": "For quantity: unit (e.g., USD, users, GW)",
            "nullable": True,
        },
        "quantity_bounds": {
            "type": "string",
            "description": "For quantity: range as min:X,max:Y",
            "nullable": True,
        },
        "estimated_start_time": {
            "type": "string",
            "description": "ISO 8601 datetime with timezone for when the question becomes forecastable (e.g. when the event was first announced). Use this when you know the specific date. Provide at least one of estimated_start_time or time_horizon_days.",
            "nullable": True,
        },
        "time_horizon": {
            "type": "string",
            "enum": ["short", "medium", "long"],
            "description": "Rough forecast lead time when the exact start date is unknown. 'short' = up to 7 days before resolution, 'medium' = ~30 days, 'long' = ~180 days. Provide at least one of estimated_start_time or time_horizon.",
            "nullable": True,
        },
    }
    output_type = "object"
    output_schema = pydantic_to_output_schema(QuestionOutput)

    def __init__(
        self,
        require_ground_truth,
        collector=None,
        existing_question_ids: Optional[set] = None,
    ):
        """Initialize the question generator.

        Args:
            collector: Optional ResultCollector[Question] for storing results.
                      If provided, questions are added to the collector instead of internal storage.
            existing_question_ids: Set of existing question IDs to skip (for deduplication)
        """
        super().__init__(collector)
        self.require_ground_truth = require_ground_truth
        self.existing_question_ids = existing_question_ids or set()

    def forward(
        self,
        question_text: str,
        question_type: str,
        domain: str,
        difficulty: int,
        resolution_date: str,
        resolution_criteria: str,
        estimated_start_time: str = None,
        time_horizon: str = None,
        related_event_ids: str = None,
        related_article_ids: str = None,
        ground_truth: str = None,
        resolution_reasoning: str = None,
        context: str = None,
        options: str = None,
        quantity_unit: str = None,
        quantity_bounds: str = None,
    ) -> str:
        """Store question data and return as structured JSON.

        Args:
            question_text: The question text
            question_type: Type of question (string, will be converted to enum)
            domain: Question domain (string, will be converted to enum)
            difficulty: Difficulty level
            resolution_date: When question can be resolved
            resolution_criteria: Objective rules for how to verify/resolve this question
            estimated_start_time: Exact ISO 8601 datetime when forecasting becomes viable
            time_horizon: 'short' / 'medium' / 'long' fallback when exact date is unknown
            related_event_ids: Optional comma-separated event IDs
            ground_truth: Optional answer if resolved
            resolution_reasoning: Optional evidence/explanation for why ground_truth is what it is
            context: Optional background information
            options: Optional MCQ choices (comma-separated)
            quantity_unit: Optional unit for quantity questions
            quantity_bounds: Optional bounds for quantity questions

        Returns:
            JSON string of Question object
        """
        # Parse resolution date
        res_date = parse_iso_datetime(
            resolution_date, fallback=datetime.now(timezone.utc) + timedelta(days=30)
        )
        res_date = ensure_timezone_aware(res_date)

        # Resolve estimated_start_time — prefer explicit date, fall back to horizon offset
        est_start_time = None
        if estimated_start_time:
            try:
                est_start_time = ensure_timezone_aware(parse_iso_datetime(estimated_start_time))
                if est_start_time >= res_date:
                    from src.utils.logging import logger
                    logger.warning(
                        f"estimated_start_time ({est_start_time}) >= resolution_date ({res_date}), ignoring"
                    )
                    est_start_time = None
            except Exception as e:
                from src.utils.logging import logger
                logger.debug(f"Failed to parse estimated_start_time: {e}")

        if est_start_time is None and time_horizon:
            _horizon_days = {
                TimeHorizon.SHORT: 7,
                TimeHorizon.MEDIUM: 30,
                TimeHorizon.LONG: 180,
            }
            try:
                horizon_enum = TimeHorizon(time_horizon)
                est_start_time = res_date - timedelta(days=_horizon_days[horizon_enum])
            except Exception as e:
                from src.utils.logging import logger
                logger.debug(f"Failed to apply time_horizon '{time_horizon}': {e}")

        if est_start_time is None and not self.require_ground_truth:
            # Future questions: default to now so the window is valid
            est_start_time = datetime.now(timezone.utc)

        # CRITICAL VALIDATION: at least one of the two must resolve for ground truth
        if self.require_ground_truth and not est_start_time:
            error_msg = (
                "REJECTED: Neither estimated_start_time nor time_horizon was provided (or both were invalid).\n"
                "For ground truth questions you MUST supply one of:\n"
                "  - estimated_start_time: ISO 8601 datetime when the question became forecastable\n"
                "  - time_horizon: 'short', 'medium', or 'long'\n"
                "Please regenerate with one of these fields."
            )
            return QuestionOutput(
                id="error",
                question_text=question_text,
                status=f"rejected: {error_msg}",
            )

        # CRITICAL VALIDATION: Ground truth questions must have past/present resolution dates
        current_time = datetime.now(timezone.utc)
        if self.require_ground_truth and res_date > current_time:
            error_msg = (
                f"REJECTED: Ground truth mode requires resolution_date <= TODAY ({current_time.date()}).\n"
                f"You provided: {res_date.date()} (FUTURE DATE)\n"
                f"This question is about a RESOLVED event - the resolution date must be when the outcome became known (in the past).\n"
                f"Please regenerate with resolution_date on or before {current_time.date()}."
            )
            return QuestionOutput(
                id="error",
                question_text=question_text,
                status=f"rejected: {error_msg}",
            )

        # CRITICAL VALIDATION: Ground truth cannot contain future dates
        if self.require_ground_truth and ground_truth:
            # Check if ground_truth contains year 2025/2026/2027 etc that's in the future
            import re

            future_date_pattern = r"(202[5-9]|20[3-9][0-9])"  # Matches 2025 onwards
            if re.search(future_date_pattern, str(ground_truth)):
                # Check if it's actually a future date
                current_year = current_time.year
                matched_years = re.findall(r"20\d{2}", str(ground_truth))
                for year_str in matched_years:
                    year = int(year_str)
                    if year > current_year:
                        error_msg = (
                            f"REJECTED: ground_truth contains FUTURE DATE (year {year}).\n"
                            f"You provided: '{ground_truth}'\n"
                            f"Ground truth must be a VERIFIED PAST OUTCOME (e.g., 'YES', 'NO', '500000', 'Apple').\n"
                            f"NEVER put future dates in ground_truth. If outcome is unknown, don't create this question."
                        )
                        return QuestionOutput(
                            id="error",
                            question_text=question_text,
                            status=f"rejected: {error_msg}",
                        )

        # CRITICAL VALIDATION: If ground_truth provided, resolution_reasoning must be provided
        if ground_truth and not resolution_reasoning:
            error_msg = (
                "REJECTED: ground_truth provided but resolution_reasoning is missing.\n"
                "When a question has a known answer (ground_truth), you MUST provide resolution_reasoning.\n"
                "The resolution_reasoning should explain the evidence/sources that confirm this answer.\n"
                "Example: 'Based on CoinMarketCap data showing BTC closed at $95,431 on Dec 31, 2024'"
            )
            return QuestionOutput(
                id="error",
                question_text=question_text,
                status="rejected: ground_truth provided but resolution_reasoning missing",
            )

        # VALIDATION: If resolution_reasoning provided without ground_truth, reject
        if resolution_reasoning and not ground_truth:
            error_msg = (
                "REJECTED: resolution_reasoning provided but ground_truth is missing.\n"
                "You can only provide resolution_reasoning for questions that have been resolved (have ground_truth).\n"
                "For unresolved questions, omit resolution_reasoning."
            )
            return QuestionOutput(
                id="error",
                question_text=question_text,
                status="rejected: resolution_reasoning provided but ground_truth missing",
            )

        # Parse event IDs
        event_ids = []
        if related_event_ids:
            event_ids = [eid.strip() for eid in related_event_ids.split(",")]

        # Parse options for MCQ questions
        options_list = None
        if options:
            options_list = [opt.strip() for opt in options.split(",")]

        # Parse quantity bounds
        bounds_dict = None
        if quantity_bounds:
            try:
                # Format: "min:X,max:Y"
                parts = quantity_bounds.split(",")
                bounds_dict = {}
                for part in parts:
                    key, value = part.split(":")
                    bounds_dict[key.strip()] = float(value.strip())
            except:
                print(
                    f"Warning: Could not parse quantity_bounds '{quantity_bounds}', expected format 'min:X,max:Y'"
                )

        # Validate and normalize enums early
        qtype_enum = QuestionType(question_type)
        domain_enum = Domain(domain)

        # Normalize ground_truth to proper type based on question_type
        normalized_ground_truth = None
        if ground_truth:
            normalized_ground_truth = self._normalize_ground_truth(
                ground_truth, qtype_enum
            )

        # Generate unique question ID using stored count
        counter = self.get_stored_count()
        question_id = self._generate_question_id(domain_enum, res_date, counter)

        # Check for duplicates - skip if this question ID already exists
        if question_id in self.existing_question_ids:
            from src.utils.logging import logger

            logger.debug(f"Skipping duplicate question: {question_id}")
            return QuestionOutput(
                id=question_id, question_text=question_text, status="skipped: duplicate"
            )

        # Determine time horizon based on resolution date
        # Use current time as reference if cutoff_date not provided
        reference_date = datetime.now(timezone.utc)
        days_until_resolution = (res_date - reference_date).days

        # Validate resolution date is reasonable (not too far in past/future)
        # The prompt should guide the agent to use appropriate dates, but we log warnings
        if days_until_resolution < -730:  # More than 2 years in the past
            print(
                f"Warning: Resolution date {res_date} is very far in the past (relative to {reference_date})"
            )
        elif days_until_resolution > 730:  # More than 2 years in the future
            print(
                f"Warning: Resolution date {res_date} is very far in the future (relative to {reference_date})"
            )

        # Create Question object
        question = Question(
            id=question_id,
            question_text=question_text,
            question_type=qtype_enum,
            domain=domain_enum,
            source="news",  # These questions are generated from news events
            difficulty=min(5, max(1, difficulty)),
            resolution_date=res_date,
            estimated_start_time=est_start_time,  # When question becomes valid for forecasting
            ground_truth=normalized_ground_truth,  # Use normalized value
            target_event_id=None,  # Deprecated: outcome events managed by OutcomeEventService
            related_event_ids=event_ids,
            related_article_ids=[aid.strip() for aid in related_article_ids.split(",")]
            if related_article_ids
            else [],
            context=context,  # Optional background information
            resolution_criteria=resolution_criteria,  # How to verify/resolve
            resolution_reasoning=resolution_reasoning,  # Why ground_truth is what it is (if resolved)
            is_synthetic=False,
            options=options_list,  # For MCQ questions
            quantity_unit=quantity_unit,  # For quantity questions
            quantity_bounds=bounds_dict,  # For quantity questions
        )

        # Store question using unified collector interface
        self.store_result(question, context=f"Question {question.id}")

        # Return QuestionOutput Pydantic model
        return QuestionOutput(
            id=question.id,
            question_text=question_text,
            status="stored",
        )

    def _generate_question_id(
        self, domain: Domain, resolution_date: datetime, counter: int
    ) -> str:
        """Generate unique question ID."""
        date_str = resolution_date.strftime("%Y%m%d")
        # Append a short UUID suffix to reduce chance of collisions/overwrites
        suffix = uuid.uuid4().hex[:8]
        # Domain is a str enum, so it works directly in f-strings
        return f"q_{domain.value}_{date_str}_{counter + 1:03d}_{suffix}"

    def _normalize_ground_truth(self, ground_truth: str, question_type: QuestionType):
        """Normalize ground_truth string to proper type based on question_type.

        Args:
            ground_truth: String representation of ground truth
            question_type: Type of question

        Returns:
            Normalized ground truth in the correct type (bool, str, float, etc.)
        """
        if not ground_truth:
            return None

        ground_truth_str = str(ground_truth).strip()

        if question_type == QuestionType.BINARY:
            # Convert to boolean for binary questions
            # Accept: YES, yes, Yes, TRUE, true, True, 1, etc.
            positive_values = {"yes", "true", "1", "y", "t"}
            negative_values = {"no", "false", "0", "n", "f"}

            lower = ground_truth_str.lower()
            if lower in positive_values:
                return True
            elif lower in negative_values:
                return False
            else:
                print(
                    f"Warning: Could not parse binary ground_truth '{ground_truth}', expected YES/NO, TRUE/FALSE, etc. Storing as None."
                )
                return None

        elif question_type == QuestionType.QUANTITY:
            # Convert to number
            try:
                # Try int first, then float
                if "." in ground_truth_str:
                    return float(ground_truth_str)
                else:
                    return int(ground_truth_str)
            except ValueError:
                print(
                    f"Warning: Could not parse quantity ground_truth '{ground_truth}' as number. Storing as None."
                )
                return None

        elif question_type == QuestionType.MCQ:
            # Keep as string (should match one of the options)
            return ground_truth_str

        elif question_type == QuestionType.TIMEFRAME:
            # Keep as string (ISO datetime or range)
            return ground_truth_str

        else:
            # Default: keep as string
            return ground_truth_str
