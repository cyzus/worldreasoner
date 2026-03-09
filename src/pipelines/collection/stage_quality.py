"""Pipeline stage for ranking questions by quality."""

from typing import List
import asyncio

from ...config.pipeline import QuestionQualityConfig
from ...core.collectors import ResultCollector
from ...domain.models.question import Question
from ...tools.generators.question_quality_scorer import (
    QuestionQualityScorer,
    QualityAssessment,
)
from src.pipelines.base import PipelineStage
from src.utils.logging import logger


class QuestionQualityRankingStage(PipelineStage[Question, Question]):
    """
    A pipeline stage that assesses and ranks questions based on quality.
    - Takes a list of questions as input.
    - Uses a QuestionQualityScorer tool to get quality assessments.
    - Attaches the quality scores to each question object.
    - Returns the list of questions with scores attached, sorted by score.
    """

    def __init__(self, config: QuestionQualityConfig, db_path: str):
        super().__init__("question_quality_ranking", config)
        self.config = config
        self.scorer = QuestionQualityScorer(
            timeout=config.timeout, dimension_weights=config.dimension_weights
        )

    async def process(self, inputs: List[Question]) -> List[Question]:
        """
        Process a list of questions to assess and attach quality scores.

        Args:
            inputs: A list of Question objects.

        Returns:
            A list of Question objects with quality_score and quality_dimensions populated,
            sorted in descending order of quality_score.
        """
        if not self.config.enabled or not inputs:
            logger.info(
                "Quality ranking stage is disabled or there are no questions to process."
            )
            return inputs

        logger.info(f"Starting quality assessment for {len(inputs)} questions...")

        # Separate already-scored from unscored questions
        already_scored = [q for q in inputs if q.quality_score is not None]
        unscored = [q for q in inputs if q.quality_score is None]

        if already_scored:
            logger.info(
                f"Skipping {len(already_scored)} questions that already have quality scores"
            )

        if not unscored:
            logger.info(
                "All questions already have quality scores, skipping assessment"
            )
            return inputs

        logger.info(f"Assessing {len(unscored)} unscored questions...")

        # Batch unscored questions only
        batches = [
            unscored[i : i + self.config.batch_size]
            for i in range(0, len(unscored), self.config.batch_size)
        ]

        logger.info(
            f"Processing in {len(batches)} batches of size up to {self.config.batch_size}."
        )

        collector = ResultCollector[QualityAssessment]()
        self.scorer.collector = collector

        tasks = [self.scorer.forward(batch) for batch in batches]
        await asyncio.gather(*tasks)

        assessments = collector.get_all()
        assessment_map = {
            assessment.question_id: assessment for assessment in assessments
        }

        logger.info(f"Received {len(assessments)} quality assessments.")

        # Process newly scored questions
        newly_scored = []
        for question in unscored:
            if question.id in assessment_map:
                assessment = assessment_map[question.id]
                question.quality_score = assessment.composite_score
                question.quality_dimensions = assessment.dimensions

                # Check if should skip evidence processing
                skip_reasons = []
                dims = assessment.dimensions

                if (
                    question.quality_score
                    < self.config.skip_thresholds["composite_score"]
                ):
                    skip_reasons.append(
                        f"composite_score too low ({question.quality_score:.2f})"
                    )
                if (
                    dims.get("verifiability", 0)
                    < self.config.skip_thresholds["verifiability"]
                ):
                    skip_reasons.append(
                        f"verifiability too low ({dims.get('verifiability', 0):.2f})"
                    )
                if (
                    dims.get("interestingness", 0)
                    < self.config.skip_thresholds["interestingness"]
                ):
                    skip_reasons.append(
                        f"not interesting enough ({dims.get('interestingness', 0):.2f})"
                    )
                if dims.get("clarity", 0) < self.config.skip_thresholds["clarity"]:
                    skip_reasons.append(
                        f"clarity too low ({dims.get('clarity', 0):.2f})"
                    )

                if skip_reasons:
                    question.skip_evidence = True
                    question.skip_reason = "; ".join(skip_reasons)
                    logger.info(
                        f"Question {question.id} marked to skip evidence: {question.skip_reason}"
                    )
                else:
                    # Check for warnings (borderline cases)
                    critical_dims = ["verifiability", "interestingness", "clarity"]
                    low_critical = [
                        dim
                        for dim in critical_dims
                        if dims.get(dim, 0)
                        < self.config.warning_thresholds["critical_dimension"]
                    ]

                    if (
                        question.quality_score
                        < self.config.warning_thresholds["composite_score"]
                    ):
                        question.quality_warning = (
                            f"Borderline quality score: {question.quality_score:.2f}"
                        )
                        logger.debug(
                            f"Question {question.id} flagged with warning: {question.quality_warning}"
                        )
                    elif low_critical:
                        dim_scores = ", ".join(
                            [f"{dim}={dims.get(dim, 0):.2f}" for dim in low_critical]
                        )
                        question.quality_warning = (
                            f"Low critical dimensions: {dim_scores}"
                        )
                        logger.debug(
                            f"Question {question.id} flagged with warning: {question.quality_warning}"
                        )

                newly_scored.append(question)
                logger.debug(
                    f"Question '{question.id}' scored: {question.quality_score:.2f}"
                )
            else:
                # If a question wasn't scored for some reason, keep it but log a warning
                logger.warning(
                    f"Question '{question.id}' was not found in assessment results."
                )
                newly_scored.append(question)  # Keep the question

        # Combine already-scored and newly-scored questions
        all_questions = already_scored + newly_scored

        # Sort all questions by quality score in descending order
        all_questions.sort(key=lambda q: q.quality_score or 0.0, reverse=True)

        logger.success(
            f"Successfully scored and ranked {len(all_questions)} questions ({len(newly_scored)} newly scored, {len(already_scored)} previously scored)."
        )

        # Log statistics for newly scored questions only
        if newly_scored:
            scores = [
                q.quality_score for q in newly_scored if q.quality_score is not None
            ]
            total = len(newly_scored)
            skipped = sum(1 for q in newly_scored if q.skip_evidence)
            warned = sum(1 for q in newly_scored if q.quality_warning)

            if scores:
                avg_score = sum(scores) / len(scores)
                min_score = min(scores)
                max_score = max(scores)
                logger.info(
                    f"Score stats: Avg={avg_score:.2f}, Min={min_score:.2f}, Max={max_score:.2f}"
                )

            logger.info(
                f"Quality decisions: {total} total, "
                f"{skipped} skip evidence ({skipped / total * 100:.1f}%), "
                f"{warned} warnings ({warned / total * 100:.1f}%)"
            )

        return all_questions
