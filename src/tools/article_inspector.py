"""Article inspector tool - analyze timeline and coverage of collected articles."""

from typing import Optional, List, Dict
from datetime import datetime

from smolagents import Tool
from src.domain.models import Article, Question
from src.core.database import GenericDatabase
from src.utils.article_analysis import (
    filter_articles_by_time_window,
    analyze_timeline,
    analyze_sources,
    identify_gaps,
    calculate_quality,
    get_recommendation
)
from src.utils.date_utils import ensure_timezone_aware
from src.utils.formatting_utils import (
    format_inspector_header,
    format_section_header,
    format_time_window,
    format_coverage_range,
    render_monthly_bar_chart,
    format_timeline_gaps,
    format_metric_line
)


class ArticleInspectorTool(Tool):
    """Inspect collected articles to identify timeline gaps and coverage issues.

    This tool helps the agent:
    1. Visualize article timeline distribution
    2. Identify time gaps that need more articles
    3. Check domain/source diversity
    4. Evaluate overall evidence coverage quality
    
    Use this tool after initial collection to determine if you need to:
    - Search for articles in specific time periods
    - Diversify sources
    - Collect more recent or historical context
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

    def __init__(self, db_path: str = "worldreasoner.db", question_id: Optional[str] = None):
        """Initialize the article inspector.

        Args:
            db_path: Path to database
            question_id: Question ID for filtering articles
        """
        super().__init__()
        self.db = GenericDatabase(db_path)
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

        # Get articles for this question
        all_articles = self.db.get_many(Article)
        question_articles = [
            a for a in all_articles
            if a.collected_for_question_id == self.question_id
        ]

        # Filter articles by time window using shared utility
        filtered_articles = filter_articles_by_time_window(
            question_articles,
            question.resolution_date,
            question.estimated_start_time
        )

        if not filtered_articles:
            return self._format_empty(question)

        # Analyze articles using shared utilities
        timeline_data = analyze_timeline(
            filtered_articles,
            question.resolution_date,
            coverage_start=question.estimated_start_time
        )
        source_data = analyze_sources(filtered_articles)
        gaps = identify_gaps(timeline_data)
        quality = calculate_quality(
            filtered_articles,
            timeline_data,
            source_data,
            gaps,
            coverage_start=question.estimated_start_time
        )

        return self._format_visualization(
            filtered_articles, timeline_data, source_data, gaps, question, quality
        )

    def _format_empty(self, question: Question) -> str:
        """Format output for no articles.

        Args:
            question: Question object

        Returns:
            Formatted empty state message
        """
        header = format_inspector_header("ARTICLE COVERAGE INSPECTOR")
        time_window_lines = format_time_window(question.resolution_date, question.estimated_start_time, indent="")
        time_window = "\n".join(time_window_lines)

        return f"""{header}
Question ID: {self.question_id}
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
        quality: Dict
    ) -> str:
        """Format the article analysis as visual text.

        Args:
            articles: List of articles
            timeline_data: Timeline statistics
            source_data: Source statistics
            gaps: Identified timeline gaps
            question: Question object with resolution_date and optional estimated_start_time
            quality: Quality metrics from calculate_quality()

        Returns:
            Formatted multi-section text
        """
        sections = []

        # Header
        sections.append(format_inspector_header("ARTICLE COVERAGE INSPECTOR"))

        # Overview
        sections.append(f"Question ID: {self.question_id}")
        sections.append(f"Total Articles: {len(articles)}")

        # Show time window
        sections.extend(format_time_window(
            question.resolution_date,
            question.estimated_start_time,
            indent=""
        ))

        sections.append("")

        # Timeline section
        if timeline_data.get("has_dates"):
            sections.extend(format_section_header("TIMELINE DISTRIBUTION"))

            # Show coverage range (considering estimated_start_time)
            earliest = timeline_data.get('earliest')
            latest = ensure_timezone_aware(question.resolution_date)
            q_start = question.estimated_start_time

            if earliest:
                # Note: For articles, we show to resolution_date (not latest article date)
                sections.extend(format_coverage_range(
                    earliest,
                    latest,
                    question.resolution_date,
                    question.estimated_start_time,
                    timeline_data['span_days'],
                    item_type="Article"
                ))

            sections.append("")

            # Monthly bar chart
            sections.extend(render_monthly_bar_chart(
                timeline_data.get('monthly', {}),
                item_type="Articles"
            ))

        # Gaps section
        if gaps:
            sections.extend(format_timeline_gaps(
                gaps,
                min_gap_label=">7 days",
                max_display=5,
                compact=False
            ))
        
        # Source diversity
        sections.extend(format_section_header("SOURCE DIVERSITY"))
        sections.append(f"  Unique Sources:  {source_data['unique_sources']}")
        sections.append(f"  Unique Domains:  {source_data['unique_domains']}")
        sections.append("")
        sections.append("  Top Sources:")
        for source, count in source_data['top_sources']:
            sections.append(f"    • {source}: {count} articles")
        sections.append("")
        
        # Coverage quality
        sections.extend(format_section_header("COVERAGE QUALITY"))
        sections.append(f"  Quality Score:  {quality['score']:.2f}/1.00")
        sections.append(f"  Volume:         {quality['volume_score']:.2f} ({len(articles)} articles)")
        sections.append(f"  Diversity:      {quality['diversity_score']:.2f} ({source_data['unique_sources']} sources)")
        sections.append(f"  Coverage:       {quality['coverage_score']:.2f} (gaps: {len(gaps)})")
        if timeline_data.get("has_dates"):
            sections.append(f"  Distribution:   {quality['distribution_score']:.2f} (evenness)")
            sections.append(f"  Gap Severity:   {quality['gap_severity']:.2f} (penalty)")
        sections.append("")

        # Recommendation
        recommendation = get_recommendation(quality, gaps, source_data, timeline_data)
        sections.extend(format_section_header("RECOMMENDATION"))
        sections.append(f"  {recommendation}")
        sections.append("")

        return "\n".join(sections)
