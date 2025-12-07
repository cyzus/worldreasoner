"""Batch question generation tool for processing multiple questions at once."""

import json
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import uuid

from smolagents import Tool
from src.domain.models import Event, Question, QuestionType, Domain
from src.utils.enums import enum_to_list
from src.utils.date_utils import parse_iso_datetime, ensure_timezone_aware
from src.utils.logging import logger
from src.tools.base import CollectorAwareTool


class BatchQuestionGeneratorTool(CollectorAwareTool[Question]):
    """Stores multiple generated forecast questions in a single call.

    This tool helps the agent:
    1. Submit ALL generated questions in one structured call
    2. Generate unique question IDs for each
    3. Link questions to source events
    4. Validate and normalize ground truth values

    Use this instead of calling question_generator multiple times to avoid
    the agent trying to use final_answer with question data.
    """

    name = "batch_question_generator"
    description = """Stores multiple generated forecast questions into structured Question format.

    Use this tool AFTER you've generated all questions.
    Call this tool ONCE with a JSON array containing ALL questions you generated.

    Args:
        questions_json (str): JSON array of question objects. Each question should have:
            - question_text (str): The actual question text
            - question_type (str): Type (boolean|mcq|quantity|timeframe)
            - domain (str): Question domain (finance|politics|tech|health|climate|sports|science|business|general)
            - difficulty (int): Difficulty level 1-5
            - resolution_date (str): When question can be resolved (ISO format)
            - resolution_criteria (str): Objective rules for verification
            - related_event_ids (str, optional): Comma-separated event IDs
            - ground_truth (str, optional): Answer if already resolved
            - resolution_reasoning (str, optional): Evidence for ground_truth (required if ground_truth provided)
            - context (str, optional): Background information
            - options (str, optional): For MCQ - comma-separated choices
            - quantity_unit (str, optional): For quantity - unit (e.g., USD, users)
            - quantity_bounds (str, optional): For quantity - range as min:X,max:Y

    Example:
        [
          {
            "question_text": "Will Bitcoin exceed $100K by end of 2025?",
            "question_type": "boolean",
            "domain": "finance",
            "difficulty": 3,
            "resolution_date": "2025-12-31",
            "resolution_criteria": "Based on CoinMarketCap closing price on Dec 31, 2025",
            "ground_truth": "YES",
            "resolution_reasoning": "Bitcoin closed at $105,432 on Dec 31, 2025 per CoinMarketCap",
            "context": "Bitcoin has been volatile in 2025...",
            "related_event_ids": "evt_finance_20251201_001"
          }
        ]

    Returns:
        str: JSON summary with count of questions stored
    """

    inputs = {
        "questions_json": {
            "type": "string",
            "description": "JSON array of question objects with all required fields"
        }
    }
    output_type = "string"

    def __init__(self, require_ground_truth: bool, collector=None, existing_question_ids: Optional[set] = None, db_path: str = None):
        """Initialize the batch question generator.

        Args:
            require_ground_truth: If True, require ground_truth for all questions
            collector: Optional ResultCollector[Question] for storing results
            existing_question_ids: Set of existing question IDs to skip
            db_path: Optional path to database for persistence
        """
        super().__init__(collector)
        self.require_ground_truth = require_ground_truth
        self.existing_question_ids = existing_question_ids or set()
        self.question_counter = 0

        # Database for persistence
        self.db = None
        if db_path:
            from src.core.database import Database
            self.db = Database(db_path)

    def forward(self, questions_json: str) -> str:
        """Store multiple questions from JSON array.

        Args:
            questions_json: JSON string containing array of question objects

        Returns:
            JSON string with summary of stored questions
        """
        try:
            # Parse the JSON array
            questions_data = json.loads(questions_json)

            if not isinstance(questions_data, list):
                return json.dumps({
                    "error": "questions_json must be a JSON array",
                    "received_type": type(questions_data).__name__,
                    "status": "failed"
                })

            stored_questions = []
            errors = []
            skipped = []

            for idx, question_data in enumerate(questions_data):
                try:
                    result = self._create_question(question_data, idx)

                    if result["status"] == "rejected":
                        errors.append({
                            "index": idx,
                            "error": result["error"],
                            "question_text": question_data.get("question_text", "")[:100]
                        })
                    elif result["status"] == "skipped":
                        skipped.append({
                            "index": idx,
                            "reason": result["reason"],
                            "id": result["id"]
                        })
                    else:
                        # Successfully created
                        question = result["question"]

                        # Store question using unified collector interface
                        self.store_result(question, context=f"Question {question.id}")

                        # Persist to database if available
                        if self.db is not None:
                            self.db.save_question(question)
                            logger.debug(f"Question {question.id} persisted to database")

                            # Update bidirectional event→question links
                            self._update_event_question_links(question)

                        stored_questions.append({
                            "id": question.id,
                            "question_type": question.question_type.value,
                            "domain": question.domain.value,
                            "difficulty": question.difficulty,
                            "question_text": question.question_text[:100] + "..." if len(question.question_text) > 100 else question.question_text
                        })

                except Exception as e:
                    errors.append({
                        "index": idx,
                        "error": str(e),
                        "question_text": question_data.get("question_text", "")[:100]
                    })
                    logger.warning(f"Failed to create question {idx}: {e}")

            summary = {
                "status": "completed",
                "total_submitted": len(questions_data),
                "successfully_stored": len(stored_questions),
                "skipped": len(skipped),
                "errors": len(errors),
                "questions": stored_questions[:5]  # Show first 5 for brevity
            }

            if errors:
                summary["error_details"] = errors[:3]  # Show first 3 errors

            if skipped:
                summary["skipped_details"] = skipped[:3]  # Show first 3 skipped

            logger.info(f"Batch question generator: {len(stored_questions)}/{len(questions_data)} questions stored successfully")

            return json.dumps(summary, indent=2)

        except json.JSONDecodeError as e:
            return json.dumps({
                "error": f"Invalid JSON format: {str(e)}",
                "status": "failed"
            })
        except Exception as e:
            logger.error(f"Batch question generator error: {e}")
            return json.dumps({
                "error": str(e),
                "status": "failed"
            })

    def _create_question(self, question_data: Dict[str, Any], index: int) -> Dict[str, Any]:
        """Create a Question object from question data dict.

        Args:
            question_data: Dictionary with question fields
            index: Index in batch (for ID generation)

        Returns:
            Dict with status and either question or error
        """
        # Required fields
        question_text = question_data.get("question_text")
        question_type = question_data.get("question_type")
        domain = question_data.get("domain")
        difficulty = question_data.get("difficulty")
        resolution_date = question_data.get("resolution_date")
        resolution_criteria = question_data.get("resolution_criteria")

        if not question_text:
            raise ValueError("Missing required field: question_text")
        if not question_type:
            raise ValueError("Missing required field: question_type")
        if not domain:
            raise ValueError("Missing required field: domain")
        if difficulty is None:
            raise ValueError("Missing required field: difficulty")
        if not resolution_date:
            raise ValueError("Missing required field: resolution_date")
        if not resolution_criteria:
            raise ValueError("Missing required field: resolution_criteria")

        # Optional fields
        related_event_ids = question_data.get("related_event_ids", "")
        ground_truth = question_data.get("ground_truth")
        resolution_reasoning = question_data.get("resolution_reasoning")
        context = question_data.get("context")
        options = question_data.get("options")
        quantity_unit = question_data.get("quantity_unit")
        quantity_bounds = question_data.get("quantity_bounds")

        # Parse resolution date
        res_date = parse_iso_datetime(
            resolution_date,
            fallback=datetime.now(timezone.utc) + timedelta(days=30)
        )
        res_date = ensure_timezone_aware(res_date)

        # CRITICAL VALIDATION: Ground truth questions must have past/present resolution dates
        current_time = datetime.now(timezone.utc)
        if self.require_ground_truth and res_date > current_time:
            error_msg = (
                f"REJECTED: Ground truth mode requires resolution_date <= TODAY ({current_time.date()}).\n"
                f"You provided: {res_date.date()} (FUTURE DATE)\n"
                f"This question is about a PAST event - the resolution date must be when the outcome became known (in the past).\n"
                f"Please regenerate with resolution_date on or before {current_time.date()}."
            )
            return {"status": "rejected", "error": error_msg}

        # CRITICAL VALIDATION: Ground truth cannot contain future dates
        if self.require_ground_truth and ground_truth:
            import re
            future_date_pattern = r'(202[5-9]|20[3-9][0-9])'
            if re.search(future_date_pattern, str(ground_truth)):
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
                        return {"status": "rejected", "error": error_msg}

        # CRITICAL VALIDATION: If ground_truth provided, resolution_reasoning must be provided
        if ground_truth and not resolution_reasoning:
            error_msg = (
                f"REJECTED: ground_truth provided but resolution_reasoning is missing.\n"
                f"When a question has a known answer (ground_truth), you MUST provide resolution_reasoning.\n"
                f"The resolution_reasoning should explain the evidence/sources that confirm this answer.\n"
                f"Example: 'Based on CoinMarketCap data showing BTC closed at $95,431 on Dec 31, 2024'"
            )
            return {"status": "rejected", "error": error_msg}

        # VALIDATION: If resolution_reasoning provided without ground_truth, reject
        if resolution_reasoning and not ground_truth:
            error_msg = (
                f"REJECTED: resolution_reasoning provided but ground_truth is missing.\n"
                f"You can only provide resolution_reasoning for questions that have been resolved (have ground_truth).\n"
                f"For unresolved questions, omit resolution_reasoning."
            )
            return {"status": "rejected", "error": error_msg}

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
                parts = quantity_bounds.split(',')
                bounds_dict = {}
                for part in parts:
                    key, value = part.split(':')
                    bounds_dict[key.strip()] = float(value.strip())
            except:
                logger.warning(f"Could not parse quantity_bounds '{quantity_bounds}', expected format 'min:X,max:Y'")

        # Validate and normalize enums early
        qtype_enum = QuestionType(question_type)
        domain_enum = Domain(domain)

        # Normalize ground_truth to proper type based on question_type
        normalized_ground_truth = None
        if ground_truth:
            normalized_ground_truth = self._normalize_ground_truth(ground_truth, qtype_enum)

        # Generate unique question ID using stored count + index
        counter = self.get_stored_count() + index
        question_id = self._generate_question_id(domain_enum, res_date, counter)

        # Check for duplicates - skip if this question ID already exists
        if question_id in self.existing_question_ids:
            logger.debug(f"Skipping duplicate question: {question_id}")
            return {
                "status": "skipped",
                "reason": "duplicate",
                "id": question_id
            }

        # Create Question object
        question = Question(
            id=question_id,
            question_text=question_text,
            question_type=qtype_enum,
            domain=domain_enum,
            source="news",  # These questions are generated from news events
            difficulty=min(5, max(1, difficulty)),
            resolution_date=res_date,
            ground_truth=normalized_ground_truth,
            target_event_id=event_ids[0] if event_ids else None,
            related_event_ids=event_ids,
            context=context,
            resolution_criteria=resolution_criteria,
            resolution_reasoning=resolution_reasoning,
            is_synthetic=False,
            options=options_list,
            quantity_unit=quantity_unit,
            quantity_bounds=bounds_dict,
        )

        return {"status": "stored", "question": question}

    def _generate_question_id(self, domain: Domain, resolution_date: datetime, counter: int) -> str:
        """Generate unique question ID."""
        date_str = resolution_date.strftime('%Y%m%d')
        suffix = uuid.uuid4().hex[:8]
        return f"q_{domain.value}_{date_str}_{counter+1:03d}_{suffix}"

    def _normalize_ground_truth(self, ground_truth: str, question_type: QuestionType):
        """Normalize ground_truth string to proper type based on question_type."""
        if not ground_truth:
            return None

        ground_truth_str = str(ground_truth).strip()

        if question_type == QuestionType.BOOLEAN:
            positive_values = {'yes', 'true', '1', 'y', 't'}
            negative_values = {'no', 'false', '0', 'n', 'f'}

            lower = ground_truth_str.lower()
            if lower in positive_values:
                return True
            elif lower in negative_values:
                return False
            else:
                logger.warning(f"Could not parse boolean ground_truth '{ground_truth}', expected YES/NO. Storing as None.")
                return None

        elif question_type == QuestionType.QUANTITY:
            try:
                if '.' in ground_truth_str:
                    return float(ground_truth_str)
                else:
                    return int(ground_truth_str)
            except ValueError:
                logger.warning(f"Could not parse quantity ground_truth '{ground_truth}' as number. Storing as None.")
                return None

        elif question_type == QuestionType.MCQ:
            return ground_truth_str

        elif question_type == QuestionType.TIMEFRAME:
            return ground_truth_str

        else:
            return ground_truth_str

    def _update_event_question_links(self, question: Question) -> None:
        """Update events to include bidirectional link to this question.

        For each event referenced by the question (target_event_id and related_event_ids),
        add this question's ID to the event's metadata['related_question_ids'].

        Args:
            question: Question to link to events
        """
        if not self.db:
            return

        from src.domain.models import Event

        # Collect all event IDs referenced by this question
        event_ids = set()
        if question.target_event_id:
            event_ids.add(question.target_event_id)
        if question.related_event_ids:
            event_ids.update(question.related_event_ids)

        if not event_ids:
            return

        for event_id in event_ids:
            try:
                # Fetch event from database
                event = self.db.db.get(Event, event_id)
                if not event:
                    logger.debug(f"Event {event_id} not found for question {question.id}")
                    continue

                # Initialize metadata if needed
                if not event.metadata:
                    event.metadata = {}

                # Initialize related_question_ids list if needed
                if 'related_question_ids' not in event.metadata:
                    event.metadata['related_question_ids'] = []

                # Check if question ID is already linked
                if question.id in event.metadata['related_question_ids']:
                    continue

                # Add question ID to event's metadata
                event.metadata['related_question_ids'].append(question.id)

                # Save updated event
                self.db.save_event(event)
                logger.debug(f"Linked event {event_id} to question {question.id}")

            except Exception as e:
                logger.warning(f"Failed to update event {event_id} for question {question.id}: {e}")
