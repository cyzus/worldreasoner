"""Question generation tool using LLM to create forecast questions from events."""

import json
from datetime import datetime, timedelta, timezone
import uuid

from smolagents import Tool
from src.domain.models import Event, Question, QuestionType, TimeHorizon, Domain
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
    description = """Stores generated forecast question into structured Question format.

    Use this tool AFTER you've created a forecast question based on events.
    Call this tool once for EACH question you generate (not all at once).

    Args:
        question_text (str): The actual question text (e.g., "Will X happen between Y and Z?")
            - For time-ranged questions: Include the range in the question text
            - For MCQ: Include context, the options will be in the 'options' parameter
            - For timeframe: Phrase as "When will X happen?" or provide time range options
        question_type (str): Type of question - MUST be one of: boolean, mcq, quantity, timeframe
            * boolean: Yes/no questions (e.g., "Will X happen by Y?")
            * mcq: Multiple choice questions (MUST provide options parameter)
            * quantity: Numerical value questions (e.g., "What percentage...", "How many...")
                - Optionally provide quantity_unit and quantity_bounds
            * timeframe: When will something happen questions
        domain (str): Question domain (finance|politics|tech|health|climate|general)
        difficulty (int): Difficulty level 1-5
        resolution_date (str): When the question can be resolved (ISO format)
            - For time-ranged questions: Use the END of the time range
            - Example: Question about "Nov 1-15" should use "2025-11-15"
        resolution_criteria (str): Clear criteria for how to resolve the question
        related_event_ids (str, optional): Comma-separated event IDs this question relates to
        ground_truth (str, optional): If already resolved, the answer
            - For boolean: "Yes" or "No"
            - For quantity: The number (e.g., "50" or "1.5 million")
            - For mcq: One of the options (e.g., "Option A")
            - For timeframe: The time it happened (e.g., "2025-12-15")
        options (str, optional): For MCQ questions - comma-separated answer choices
            - Example: "Option A: Before Dec 2025,Option B: Jan-Mar 2026,Option C: After Jun 2026"
        quantity_unit (str, optional): For quantity questions - the unit (e.g., "USD", "users", "GW")
        quantity_bounds (str, optional): For quantity questions - valid range in format "min:X,max:Y"
            - Example: "min:0,max:100" for percentages

    Returns:
        str: JSON string with the created Question object including generated ID
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
        "resolution_criteria": {"type": "string", "description": "How to resolve the question"},
        "related_event_ids": {"type": "string", "description": "Comma-separated event IDs", "nullable": True},
        "ground_truth": {"type": "string", "description": "Answer if already resolved", "nullable": True},
        "options": {"type": "string", "description": "For MCQ: comma-separated answer choices", "nullable": True},
        "quantity_unit": {"type": "string", "description": "For quantity: unit (e.g., USD, users, GW)", "nullable": True},
        "quantity_bounds": {"type": "string", "description": "For quantity: range as min:X,max:Y", "nullable": True},
    }
    output_type = "string"  # JSON string
    
    def __init__(self, collector=None):
        """Initialize the question generator.
        
        Args:
            collector: Optional ResultCollector[Question] for storing results.
                      If provided, questions are added to the collector instead of internal storage.
        """
        super().__init__()
        # Result storage - use collector if provided, otherwise internal list
        self.collector = collector
        self.generated_questions = []  # Fallback for backward compatibility
    
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

        # Validate and convert question_type
        valid_types = ["boolean", "mcq", "quantity", "timeframe"]
        common_mistakes = {
            "numeric": "quantity",
            "multiple_choice": "mcq",
            "number": "quantity",
            "multiplechoice": "mcq",
            "bool": "boolean",
            "yes_no": "boolean"
        }

        # Normalize input (lowercase)
        q_type_normalized = question_type.lower() if question_type else "boolean"

        # Check for common mistakes
        if q_type_normalized in common_mistakes:
            correct_type = common_mistakes[q_type_normalized]
            raise ValueError(
                f"Invalid question_type '{question_type}'. "
                f"Did you mean '{correct_type}'? "
                f"Valid types are: {', '.join(valid_types)}"
            )

        # Validate against QuestionType enum
        try:
            q_type_enum = QuestionType(q_type_normalized)
        except ValueError:
            raise ValueError(
                f"Invalid question_type '{question_type}'. "
                f"Must be EXACTLY one of: {', '.join(valid_types)} (case-insensitive)"
            )

        # Validate and convert domain
        try:
            domain_enum = Domain(domain.lower() if domain else "general")
        except ValueError:
            # Fall back to general if invalid
            print(f"Warning: Invalid domain '{domain}', using 'general'")
            domain_enum = Domain.GENERAL

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

        # Determine time horizon based on resolution date
        if days_until_resolution <= 30:
            horizon = TimeHorizon.SHORT
        elif days_until_resolution <= 180:
            horizon = TimeHorizon.MEDIUM
        else:
            horizon = TimeHorizon.LONG

        # Create Question object
        question = Question(
            id=question_id,
            question_text=question_text,
            question_type=q_type_enum,
            domain=domain_enum,
            difficulty=min(5, max(1, difficulty)),
            time_horizon=horizon,
            resolution_date=res_date,
            resolution_criteria=resolution_criteria,
            ground_truth=ground_truth,
            target_event_id=event_ids[0] if event_ids else None,
            related_event_ids=event_ids,
            context=resolution_criteria[:300],  # Use criteria as context
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
            "domain": question.domain,
            "difficulty": question.difficulty,
            "time_horizon": question.time_horizon.value,
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

