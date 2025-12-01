"""Pipeline stage for ranking questions by quality."""

from typing import List
import asyncio

from ...config.pipeline import QuestionQualityConfig
from ...core.collectors import ResultCollector
from ...domain.models.question import Question
from ...tools.question_quality_scorer import QuestionQualityScorer, QualityAssessment
from ..base import PipelineStage, PipelineStageResult
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
        super().__init__("question_quality_ranking", {"config": config.dict()})
        self.config = config
        self.scorer = QuestionQualityScorer(timeout=config.timeout)

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
            logger.info("Quality ranking stage is disabled or there are no questions to process.")
            return inputs

        logger.info(f"Starting quality assessment for {len(inputs)} questions...")

        # Batch questions
        batches = [
            inputs[i:i + self.config.batch_size]
            for i in range(0, len(inputs), self.config.batch_size)
        ]

        logger.info(f"Processing in {len(batches)} batches of size up to {self.config.batch_size}.")

        collector = ResultCollector[QualityAssessment]()
        self.scorer.collector = collector

        tasks = [self.scorer.forward(batch) for batch in batches]
        await asyncio.gather(*tasks)

        assessments = collector.get_all()
        assessment_map = {assessment.question_id: assessment for assessment in assessments}

        logger.info(f"Received {len(assessments)} quality assessments.")

        scored_questions = []
        for question in inputs:
            if question.id in assessment_map:
                assessment = assessment_map[question.id]
                question.quality_score = assessment.composite_score
                question.quality_dimensions = assessment.dimensions
                scored_questions.append(question)
                logger.debug(f"Question '{question.id}' scored: {question.quality_score:.2f}")
            else:
                # If a question wasn't scored for some reason, keep it but log a warning
                logger.warning(f"Question '{question.id}' was not found in assessment results.")
                scored_questions.append(question) # Keep the question

        # Sort questions by quality score in descending order
        scored_questions.sort(key=lambda q: q.quality_score or 0.0, reverse=True)

        logger.success(f"Successfully scored and ranked {len(scored_questions)} questions.")
        
        # Log score distribution for analysis
        if scored_questions:
            scores = [q.quality_score for q in scored_questions if q.quality_score is not None]
            if scores:
                avg_score = sum(scores) / len(scores)
                min_score = min(scores)
                max_score = max(scores)
                logger.info(f"Score stats: Avg={avg_score:.2f}, Min={min_score:.2f}, Max={max_score:.2f}")

        return scored_questions
