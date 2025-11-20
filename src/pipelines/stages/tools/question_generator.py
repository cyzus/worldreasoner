"""Question generation tool using LLM to create forecast questions from events."""

import json
from datetime import datetime, timedelta, timezone
import uuid

from smolagents import Tool
from src.domain.models import Event, Question, QuestionType, Domain
from src.utils.enums import enum_to_list


class QuestionGeneratorTool(Tool):
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
    description = """Stores a generated forecast question as a structured Question object.

    Use this tool AFTER you've created a forecast question based on events.
    Call this tool once for EACH question you generate (not all at once).
    """
    
    # Auto-generate inputs from Enum classes (single source of truth)
    inputs = {
        "question_text": {"type": "string", "description": "The actual question text"},
        "question_type": {
            "type": "string",
            "description": f"Question type - MUST be one of: {', '.join(enum_to_list(QuestionType))}",
            "enum": enum_to_list(QuestionType)
        },
        "domain": {
            "type": "string",
            "description": f"Question domain - one of: {', '.join(enum_to_list(Domain))}",
            "enum": enum_to_list(Domain)
        },
        "difficulty": {"type": "integer", "description": "Difficulty level 1-5"},
        "resolution_date": {"type": "string", "description": "When question can be resolved (ISO format)"},
        "resolution_criteria": {"type": "string", "description": "How to resolve the question or what makes the provided answer correct"},
        "related_event_ids": {"type": "string", "description": "Comma-separated event IDs", "nullable": True},
        "ground_truth": {"type": "string", "description": "Answer if already resolved", "nullable": True},
        "options": {"type": "string", "description": "For MCQ: comma-separated answer choices", "nullable": True},
        "quantity_unit": {"type": "string", "description": "For quantity: unit (e.g., USD, users, GW)", "nullable": True},
        "quantity_bounds": {"type": "string", "description": "For quantity: range as min:X,max:Y", "nullable": True},
    }
    output_type = "string"  # JSON string
    
    def __init__(self, require_ground_truth, collector=None):
        """Initialize the question generator.

        Args:
            collector: Optional ResultCollector[Question] for storing results.
                      If provided, questions are added to the collector instead of internal storage.
        """
        super().__init__()
        # Result storage - use collector if provided, otherwise internal list
        self.collector = collector
        self.require_ground_truth = require_ground_truth
        # Backward compatibility: internal storage when no collector provided
        self.generated_questions = []
    
    def forward(
        self,
        question_text: str,
        question_type: str,
        domain: str,
        difficulty: int,
        resolution_date: str,
        resolution_criteria: str,
        related_event_ids: str = None,
        ground_truth: str = None,
        options: str = None,
        quantity_unit: str = None,
        quantity_bounds: str = None
    ) -> str:
        """Store question data and return as structured JSON.

        Args:
            question_text: The question text
            question_type: Type of question (string, will be converted to enum)
            domain: Question domain (string, will be converted to enum)
            difficulty: Difficulty level
            resolution_date: When question can be resolved
            resolution_criteria: How to resolve
            related_event_ids: Optional comma-separated event IDs
            ground_truth: Optional answer if resolved
            options: Optional MCQ choices (comma-separated)
            quantity_unit: Optional unit for quantity questions
            quantity_bounds: Optional bounds for quantity questions

        Returns:
            JSON string of Question object
        """
        # Parse resolution date
        try:
            res_date = datetime.fromisoformat(resolution_date.replace('Z', '+00:00'))
            # Ensure timezone-aware (add UTC if naive)
            if res_date.tzinfo is None:
                res_date = res_date.replace(tzinfo=timezone.utc)
        except:
            res_date = datetime.now(timezone.utc) + timedelta(days=30)

        # CRITICAL VALIDATION: Ground truth questions must have past/present resolution dates
        current_time = datetime.now(timezone.utc)
        if self.require_ground_truth and res_date > current_time:
            error_msg = (
                f"REJECTED: Ground truth mode requires resolution_date <= TODAY ({current_time.date()}).\n"
                f"You provided: {res_date.date()} (FUTURE DATE)\n"
                f"This question is about a PAST event - the resolution date must be when the outcome became known (in the past).\n"
                f"Please regenerate with resolution_date on or before {current_time.date()}."
            )
            return json.dumps({"error": error_msg, "status": "rejected"})

        # CRITICAL VALIDATION: Ground truth cannot contain future dates
        if self.require_ground_truth and ground_truth:
            # Check if ground_truth contains year 2025/2026/2027 etc that's in the future
            import re
            future_date_pattern = r'(202[5-9]|20[3-9][0-9])'  # Matches 2025 onwards
            if re.search(future_date_pattern, str(ground_truth)):
                # Check if it's actually a future date
                current_year = current_time.year
                matched_years = re.findall(r'20\d{2}', str(ground_truth))
                for year_str in matched_years:
                    year = int(year_str)
                    if year > current_year:
                        error_msg = (
                            f"REJECTED: ground_truth contains FUTURE DATE (year {year}).\n"
                            f"You provided: '{ground_truth}'\n"
                            f"Ground truth must be a VERIFIED PAST OUTCOME (e.g., 'YES', 'NO', '500000', 'Apple').\n"
                            f"NEVER put future dates in ground_truth. If outcome is unknown, don't create this question."
                        )
                        return json.dumps({"error": error_msg, "status": "rejected"})

        # Parse event IDs
        event_ids = []
        if related_event_ids:
            event_ids = [eid.strip() for eid in related_event_ids.split(',')]

        # Parse options for MCQ questions
        options_list = None
        if options:
            options_list = [opt.strip() for opt in options.split(',')]

        # Parse quantity bounds
        bounds_dict = None
        if quantity_bounds:
            try:
                # Format: "min:X,max:Y"
                parts = quantity_bounds.split(',')
                bounds_dict = {}
                for part in parts:
                    key, value = part.split(':')
                    bounds_dict[key.strip()] = float(value.strip())
            except:
                print(f"Warning: Could not parse quantity_bounds '{quantity_bounds}', expected format 'min:X,max:Y'")


        # Validate and normalize enums early
        qtype_enum = QuestionType(question_type)
        domain_enum = Domain(domain)

        # Normalize ground_truth to proper type based on question_type
        normalized_ground_truth = None
        if ground_truth:
            normalized_ground_truth = self._normalize_ground_truth(ground_truth, qtype_enum)

        # Generate unique question ID (use collector count as counter if available, otherwise generated_questions)
        counter = len(self.collector) if self.collector is not None else len(self.generated_questions)
        question_id = self._generate_question_id(domain_enum, res_date, counter)

        # Determine time horizon based on resolution date
        # Use current time as reference if cutoff_date not provided
        reference_date = datetime.now(timezone.utc)
        days_until_resolution = (res_date - reference_date).days

        # Validate resolution date is reasonable (not too far in past/future)
        # The prompt should guide the agent to use appropriate dates, but we log warnings
        if days_until_resolution < -730:  # More than 2 years in the past
            print(f"Warning: Resolution date {res_date} is very far in the past (relative to {reference_date})")
        elif days_until_resolution > 730:  # More than 2 years in the future
            print(f"Warning: Resolution date {res_date} is very far in the future (relative to {reference_date})")

        # Create Question object
        question = Question(
            id=question_id,
            question_text=question_text,
            question_type=qtype_enum,
            domain=domain_enum,
            difficulty=min(5, max(1, difficulty)),
            resolution_date=res_date,
            ground_truth=normalized_ground_truth,  # Use normalized value
            target_event_id=event_ids[0] if event_ids else None,
            related_event_ids=event_ids,
            context=resolution_criteria,  # Use criteria as context
            is_synthetic=False,
            options=options_list,  # For MCQ questions
            quantity_unit=quantity_unit,  # For quantity questions
            quantity_bounds=bounds_dict,  # For quantity questions
        )
        
        # Store full question using collector if provided, otherwise use internal list
        # Note: Check 'is not None' because ResultCollector.__bool__ returns False when empty
        if self.collector is not None:
            self.collector.add(question)
        else:
            # Backward compatibility - store in internal list
            self.generated_questions.append(question)
        
        # Return summary to save tokens (NOT full question)
        summary = {
            "id": question.id,
            "question_text": question_text[:200] + "..." if len(question_text) > 200 else question_text,
            "question_type": question.question_type.value,
            "domain": question.domain.value,
            "difficulty": question.difficulty,
            "resolution_date": question.resolution_date.isoformat(),
            "status": "stored"
        }
        
        return json.dumps(summary, indent=2, default=str)
    
    def _generate_question_id(self, domain: Domain, resolution_date: datetime, counter: int) -> str:
        """Generate unique question ID."""
        date_str = resolution_date.strftime('%Y%m%d')
        # Append a short UUID suffix to reduce chance of collisions/overwrites
        suffix = uuid.uuid4().hex[:8]
        # Domain is a str enum, so it works directly in f-strings
        return f"q_{domain.value}_{date_str}_{counter+1:03d}_{suffix}"

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

        if question_type == QuestionType.BOOLEAN:
            # Convert to boolean
            # Accept: YES, yes, Yes, TRUE, true, True, 1, etc.
            positive_values = {'yes', 'true', '1', 'y', 't'}
            negative_values = {'no', 'false', '0', 'n', 'f'}

            lower = ground_truth_str.lower()
            if lower in positive_values:
                return True
            elif lower in negative_values:
                return False
            else:
                print(f"Warning: Could not parse boolean ground_truth '{ground_truth}', expected YES/NO, TRUE/FALSE, etc. Storing as None.")
                return None

        elif question_type == QuestionType.QUANTITY:
            # Convert to number
            try:
                # Try int first, then float
                if '.' in ground_truth_str:
                    return float(ground_truth_str)
                else:
                    return int(ground_truth_str)
            except ValueError:
                print(f"Warning: Could not parse quantity ground_truth '{ground_truth}' as number. Storing as None.")
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

