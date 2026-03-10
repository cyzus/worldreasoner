"""Prompts for assessing the quality of forecast questions."""

from textwrap import dedent

# ==============================================================================
# STRUCTURED OUTPUT SCHEMA (for parsing LLM response)
# ==============================================================================

QUALITY_ASSESSMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "assessments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question_id": {"type": "string"},
                    "composite_score": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                    "dimensions": {
                        "type": "object",
                        "properties": {
                            "interestingness": {
                                "type": "number",
                                "minimum": 0.0,
                                "maximum": 1.0,
                            },
                            "clarity": {
                                "type": "number",
                                "minimum": 0.0,
                                "maximum": 1.0,
                            },
                            "verifiability": {
                                "type": "number",
                                "minimum": 0.0,
                                "maximum": 1.0,
                            },
                            "temporal_validity": {
                                "type": "number",
                                "minimum": 0.0,
                                "maximum": 1.0,
                            },
                            "context_sufficiency": {
                                "type": "number",
                                "minimum": 0.0,
                                "maximum": 1.0,
                            },
                            "difficulty_appropriateness": {
                                "type": "number",
                                "minimum": 0.0,
                                "maximum": 1.0,
                            },
                            "format_consistency": {
                                "type": "number",
                                "minimum": 0.0,
                                "maximum": 1.0,
                            },
                        },
                        "required": [
                            "interestingness",
                            "clarity",
                            "verifiability",
                            "temporal_validity",
                            "context_sufficiency",
                            "difficulty_appropriateness",
                            "format_consistency",
                        ],
                    },
                    "reasoning": {"type": "string"},
                },
                "required": [
                    "question_id",
                    "composite_score",
                    "dimensions",
                    "reasoning",
                ],
            },
        }
    },
    "required": ["assessments"],
}


# ==============================================================================
# PROMPT TEMPLATE FOR QUESTION QUALITY ASSESSMENT
# ==============================================================================

_quality_assessment_template = dedent("""
    You are a meticulous analyst responsible for quality control in a forecasting benchmark system.
    Your task is to assess a batch of forecast questions based on a set of quality dimensions.
    Provide a score from 0.0 (terrible) to 1.0 (excellent) for each dimension, and a final composite score.

    **ASSESSMENT CRITERIA**

    1.  **Interestingness (0.0-1.0)**:
        - 1.0: A highly engaging question about a significant, non-trivial future event.
        - 0.5: Moderately interesting, but may be niche or have limited impact.
        - 0.0: A dull, trivial, or overly esoteric question.

    2.  **Clarity (0.0-1.0)**:
        - 1.0: Unambiguous, well-defined, and easily understood.
        - 0.5: Mostly clear, but with minor ambiguities.
        - 0.0: Vague, confusing, or poorly worded.

    3.  **Verifiability (0.0-1.0)**:
        - 1.0: Has objective, clear resolution criteria for determining the ground truth.
        - 0.5: Resolution criteria are present but somewhat subjective or hard to check.
        - 0.0: No clear way to objectively verify the outcome.

    4.  **Temporal Validity (0.0-1.0)**:
        - 1.0: The resolution date is logical and appropriate for the event in question.
        - 0.5: The resolution date is plausible but might be too far in the future or awkwardly timed.
        - 0.0: The resolution date is nonsensical or irrelevant.

    5.  **Context Sufficiency (0.0-1.0)**:
        - 1.0: Provides all necessary background information for a well-informed forecast.
        - 0.5: Provides some context, but key details are missing.
        - 0.0: Lacks essential context, making forecasting difficult.

    6.  **Difficulty Appropriateness (0.0-1.0)**:
        - 1.0: The assigned difficulty rating (1-5) accurately reflects the question's complexity.
        - 0.5: The difficulty rating is off by one or two levels.
        - 0.0: The difficulty rating is completely mismatched with the question.

    7.  **Format Consistency (0.0-1.0)**:
        - 1.0: The question type (e.g., boolean, MCQ) and its supporting fields (e.g., options for MCQ) are perfectly consistent.
        - 0.5: Minor inconsistencies, like a boolean question phrased as a "which" question.
        - 0.0: Major format errors, like an MCQ with no options.

    **BATCH OF QUESTIONS TO ASSESS**

    Here is a batch of {num_questions} questions in JSON format.
    Please evaluate each one according to the criteria above.

    ```json
    {questions_json}
    ```

    **INSTRUCTIONS**

    1.  Carefully review each question in the batch.
    2.  For each question, score all 7 dimensions from 0.0 to 1.0.
    3.  Calculate a composite score as the unweighted average of the 7 dimension scores.
        Note: The system will recalculate this using weighted averaging (verifiability=25%, interestingness=20%, clarity=20%, temporal_validity=15%, context_sufficiency=10%, difficulty_appropriateness=5%, format_consistency=5%).
    4.  Provide a brief, one-sentence reasoning for your assessment, focusing on the most critical dimensions (verifiability, interestingness, clarity).
    5.  Return your assessment as a single JSON object matching the required schema. Do not add any commentary outside the JSON object.
    
    The output format MUST be a JSON object with a single key "assessments", which is a list of assessment objects.
    Example for a single question assessment:
    {{
      "question_id": "q_123",
      "composite_score": 0.85,
      "dimensions": {{
        "interestingness": 0.9,
        "clarity": 1.0,
        "verifiability": 0.8,
        "temporal_validity": 1.0,
        "context_sufficiency": 0.7,
        "difficulty_appropriateness": 0.8,
        "format_consistency": 0.9
      }},
      "reasoning": "A clear, verifiable, and interesting question, though the context could be slightly more detailed."
    }}
""")

QUESTION_QUALITY_ASSESSMENT_PROMPT = _quality_assessment_template
