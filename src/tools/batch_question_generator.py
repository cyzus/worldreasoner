"""Batch question generation tool for processing multiple questions at once."""

import json
from typing import List, Dict, Any, Optional

from src.domain.models import Event, Question, Domain, QuestionType
from src.utils.logging import logger
from src.utils.enums import enum_to_list
from src.tools.question_generator import QuestionGeneratorTool


class BatchQuestionGeneratorTool(QuestionGeneratorTool):
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
    description = f"""Stores multiple generated forecast questions into structured Question format.

    Use this tool AFTER you've generated all questions.
    Call this tool ONCE with a JSON array containing ALL questions you generated.

    Args:
        questions_json (str): JSON array of question objects. Each question should have:
            - question_text (str): The actual question text
            - question_type (str): Type - one of: {', '.join(enum_to_list(QuestionType))}
            - domain (str): Question domain - one of: {', '.join(enum_to_list(Domain))}
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
            - estimated_start_time (str, optional): When question becomes valid for forecasting (ISO format, MUST be before resolution_date)

    Example:
        [
          {{
            "question_text": "Will Bitcoin exceed $100K by end of 202X?",
            "question_type": "binary",
            "domain": "finance",
            "difficulty": 3,
            "resolution_date": "202X-12-31T23:59:59Z",
            "resolution_criteria": "Based on CoinMarketCap closing price on Dec 31, 202X",
            "ground_truth": "YES",
            "resolution_reasoning": "Bitcoin closed at $105,432 on Dec 31, 202X per CoinMarketCap",
            "context": "Bitcoin has been volatile in 202X...",
            "related_event_ids": "evt_finance_202X1201_001",
            "estimated_start_time": "202X-01-01T00:00:00Z"
          }}
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
        super().__init__(require_ground_truth=require_ground_truth, collector=collector, existing_question_ids=existing_question_ids)
        self.question_counter = 0

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
                    # Use parent class forward method to process single question
                    result_json = super().forward(
                        question_text=question_data.get("question_text"),
                        question_type=question_data.get("question_type"),
                        domain=question_data.get("domain"),
                        difficulty=question_data.get("difficulty"),
                        resolution_date=question_data.get("resolution_date"),
                        resolution_criteria=question_data.get("resolution_criteria"),
                        related_event_ids=question_data.get("related_event_ids"),
                        ground_truth=question_data.get("ground_truth"),
                        resolution_reasoning=question_data.get("resolution_reasoning"),
                        context=question_data.get("context"),
                        options=question_data.get("options"),
                        quantity_unit=question_data.get("quantity_unit"),
                        quantity_bounds=question_data.get("quantity_bounds"),
                        estimated_start_time=question_data.get("estimated_start_time")
                    )
                    
                    result = json.loads(result_json)
                    
                    if result.get("status") == "rejected":
                        errors.append({
                            "index": idx,
                            "error": result.get("error"),
                            "question_text": question_data.get("question_text", "")[:100]
                        })
                    elif result.get("status") == "skipped":
                        skipped.append({
                            "index": idx,
                            "reason": result.get("reason"),
                            "id": result.get("id")
                        })
                    else:
                        # Successfully created
                        stored_questions.append({
                            "id": result.get("id"),
                            "question_type": result.get("question_type"),
                            "domain": result.get("domain"),
                            "difficulty": result.get("difficulty"),
                            "question_text": result.get("question_text")
                        })

                        # Update bidirectional event→question links if we have database wrapper
                        if hasattr(self, '_db_wrapper') and self._db_wrapper is not None:
                            # Get the stored question to update links
                            from src.domain.models import Question
                            question = self.get_stored_items()[-1]  # Get last stored question
                            if question:
                                self._update_event_question_links(question)

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

    def _update_event_question_links(self, question: Question) -> None:
        """Update events to include bidirectional link to this question.

        For each event referenced by the question (target_event_id and related_event_ids),
        add this question's ID to the event's metadata['related_question_ids'].

        Args:
            question: Question to link to events
        """
        # Note: QuestionGeneratorTool doesn't have self.db, so this method won't work
        # unless we add database support to the parent class
        return
