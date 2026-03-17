"""Article inspector tool - analyze timeline and coverage of collected articles."""

from typing import Optional, List, Dict

from src.tools.base.database_mixin import DatabaseAwareTool
from src.services.question_monitor_service import QuestionMonitorService
from src.domain.models import Article, Question
from src.analysis.article_analysis import (
    analyze_timeline,
    analyze_sources,
    identify_gaps,
    calculate_quality,
    get_recommendation,
)
from src.services.temporal_filter_service import TemporalFilterService
from src.utils.date_utils import ensure_timezone_aware
from src.tools.inspectors.formatting import (
    InspectorReportBuilder,
    format_inspector_header,
    format_time_window,
)


class ArticleInspectorTool(DatabaseAwareTool):
    """Inspect collected articles to identify timeline gaps and coverage issues.

    Computes a quality score (0–1) weighted: coverage 40%, volume 35%,
    diversity 25%. Coverage penalises gaps > 7 days and uneven distribution.
    Volume saturates at 10 articles; diversity saturates at ~9 unique sources.

    See docs/inspectors.md for full scoring criteria and thresholds.
    """

    name = "article_inspector"
    description = """Analyze timeline and coverage of collected articles.

    Evaluates coverage relative to the question resolution date:
    - Timeline distribution (articles published before resolution)
    - Time gaps that need filling
    - Source diversity (how many different sources)
    - Coverage quality score

    Returns:
        Text visualization showing timeline, gaps, and recommendations
    """

    inputs = {}
    output_type = "string"

    def __init__(
        self, db_path: str = "worldreasoner.db", question_id: Optional[str] = None
    ):
        """Initialize the article inspector.

        Args:
            db_path: Path to database
            question_id: Question ID for filtering articles
        """
        super().__init__(db_path=db_path, ensure_tables=[Article, Question])
        self.question_id = question_id

    def forward(self) -> str:
        """Analyze article collection timeline and coverage.

        Returns:
            Formatted text with timeline visualization and recommendations
        """
        if not self.question_id:
            return self._format_error("No question context provided")

        # Get question for resolution date and estimated_start_time
        question = self.db.get(Question, self.question_id)
        if not question:
            return self._format_error(f"Question {self.question_id} not found")

        # Get articles for this question efficiently
        question_articles = self.db.get_many(
            Article, filters={"collected_for_question_id": self.question_id}
        )

        # Filter articles by time window
        window_start, window_end = TemporalFilterService.get_evidence_window(
            question.resolution_date, question.estimated_start_time
        )
        filtered_articles = TemporalFilterService.filter_by_window(
            question_articles, window_start, window_end
        )

        if not filtered_articles:
            return self._format_empty(question)

        # Analyze articles using shared utilities
        timeline_data = analyze_timeline(
            filtered_articles,
            question.resolution_date,
            coverage_start=question.estimated_start_time,
        )
        source_data = analyze_sources(filtered_articles)
        gaps = identify_gaps(timeline_data)
        monitor = QuestionMonitorService(self.db)
        quality = calculate_quality(
            filtered_articles,
            timeline_data,
            source_data,
            gaps,
            coverage_start=question.estimated_start_time,
            min_articles=monitor.config.min_articles,
        )

        return self._format_visualization(
            filtered_articles, timeline_data, source_data, gaps, question, quality, monitor
        )

    def _format_empty(self, question: Question) -> str:
        """Format output for no articles.

        Args:
            question: Question object

        Returns:
            Formatted empty state message
        """
        header = format_inspector_header("ARTICLE COVERAGE INSPECTOR")
        time_window_lines = format_time_window(
            question.resolution_date, question.estimated_start_time, indent=""
        )
        time_window = "\n".join(time_window_lines)

        return f"""{header}
{time_window}

STATUS: No Articles Collected
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

No valid articles have been collected for this question's time window.

RECOMMENDATION:
→ Start evidence collection with web_search and article_collector
→ Search for articles covering the key events and time period
→ Aim for 5-10 diverse articles from different sources
"""

    def _format_error(self, error: str) -> str:
        """Format error message."""
        header = format_inspector_header("ARTICLE COVERAGE INSPECTOR")
        return f"""{header}
ERROR: {error}
"""

    def _format_visualization(
        self,
        articles: List[Article],
        timeline_data: Dict,
        source_data: Dict,
        gaps: List[Dict],
        question: Question,
        quality: Dict,
        monitor: QuestionMonitorService,
    ) -> str:
        """Format the article analysis as visual text."""
        builder = InspectorReportBuilder("ARTICLE COVERAGE INSPECTOR")

        # Overview
        builder.add_kv("Question Title", question.question_text)
        builder.add_kv("Total Articles", len(articles))
        builder.add_time_window(
            question.resolution_date, question.estimated_start_time, indent=0
        )
        builder.add_line()

        # Timeline section
        if timeline_data.get("has_dates"):
            builder.add_section_header("TIMELINE DISTRIBUTION")

            # Coverage range
            earliest = timeline_data.get("earliest")
            if earliest:
                builder.add_coverage_range(
                    earliest,
                    ensure_timezone_aware(question.resolution_date),
                    question.resolution_date,
                    question.estimated_start_time,
                    item_type="Article",
                )
                builder.add_line()

            # Monthly bar chart
            builder.add_monthly_bar_chart(
                timeline_data.get("monthly", {}), item_type="Articles"
            )

        # Gaps section
        if gaps:
            builder.add_timeline_gaps(
                gaps, min_gap_label=">7 days", max_display=5, compact=False
            )

        # Source diversity
        builder.add_section_header("SOURCE DIVERSITY")
        builder.add_kv("Unique Sources", source_data["unique_sources"], indent=2)
        builder.add_kv("Unique Domains", source_data["unique_domains"], indent=2)
        builder.add_line()
        builder.add_line("Top Sources:", indent=2)
        for source, count in source_data["top_sources"]:
            builder.add_line(f"• {source}: {count} articles", indent=4)
        builder.add_line()

        # Coverage quality
        builder.add_section_header("COVERAGE QUALITY")
        metrics = {
            "Quality Score": quality["score"],
            "Volume": quality["volume_score"],
            "Diversity": quality["diversity_score"],
            "Coverage": quality["coverage_score"],
        }
        if timeline_data.get("has_dates"):
            metrics.update(
                {
                    "Distribution": quality["distribution_score"],
                    "Gap Severity": quality["gap_severity"],
                }
            )

        builder.add_metrics(metrics)
        builder.add_line()

        # Recommendation
        missing_reqs = monitor.evaluate_article_requirements(
            len(articles), question.causal_explanation
        )
        recommendation = get_recommendation(
            quality,
            gaps,
            source_data,
            timeline_data,
            min_articles=monitor.config.min_articles,
        )
        if missing_reqs:
            recommendation += f"\nRequirements not met: {'; '.join(missing_reqs)}"
        builder.add_section_header("RECOMMENDATION")
        builder.add_line(recommendation, indent=2)
        builder.add_line()

        return builder.build()
