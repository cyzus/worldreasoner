"""Article inspector tool - analyze timeline and coverage of collected articles."""

from typing import Optional, List, Dict
from collections import defaultdict
from datetime import datetime, timedelta

from smolagents import Tool
from src.domain.models import Article, Question
from src.core.database import GenericDatabase


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

    NO INPUT REQUIRED - automatically uses the current question context.

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

        # Get question for resolution date
        question = self.db.get(Question, self.question_id)
        if not question:
            return self._format_error(f"Question {self.question_id} not found")

        # Get articles published before resolution date
        all_articles = self.db.get_many(Article)
        question_articles = [
            a for a in all_articles
            if a.collected_for_question_id == self.question_id
            and (not a.published_date or a.published_date < question.resolution_date)
        ]

        if not question_articles:
            return self._format_empty()

        # Analyze articles
        timeline_data = self._analyze_timeline(question_articles, question.resolution_date)
        source_data = self._analyze_sources(question_articles)
        gaps = self._identify_gaps(timeline_data, question_articles)

        return self._format_visualization(
            question_articles, timeline_data, source_data, gaps, question.resolution_date
        )

    def _analyze_timeline(self, articles: List[Article], resolution_date: datetime) -> Dict:
        """Analyze temporal distribution of articles.

        Args:
            articles: List of articles
            resolution_date: Question resolution date (coverage endpoint)

        Returns:
            Timeline statistics
        """
        dates = [a.published_date for a in articles if a.published_date]

        if not dates:
            return {"has_dates": False, "resolution_date": resolution_date}

        dates.sort()
        earliest = dates[0]
        span_days = (resolution_date - earliest).days

        # Group by month for visualization
        monthly = defaultdict(int)
        for date in dates:
            month_key = date.strftime("%Y-%m")
            monthly[month_key] += 1

        return {
            "has_dates": True,
            "earliest": earliest,
            "resolution_date": resolution_date,
            "span_days": span_days,
            "monthly": dict(monthly),
            "dates": dates
        }

    def _analyze_sources(self, articles: List[Article]) -> Dict:
        """Analyze source diversity.

        Args:
            articles: List of articles

        Returns:
            Source statistics
        """
        sources = defaultdict(int)
        domains = set()

        for article in articles:
            if article.source:
                sources[article.source] += 1
            if article.domain:
                domains.add(article.domain)

        return {
            "unique_sources": len(sources),
            "unique_domains": len(domains),
            "source_counts": dict(sources),
            "top_sources": sorted(sources.items(), key=lambda x: x[1], reverse=True)[:5]
        }

    def _identify_gaps(self, timeline_data: Dict, articles: List[Article]) -> List[Dict]:
        """Identify significant time gaps in coverage.

        Args:
            timeline_data: Timeline analysis data
            articles: List of articles

        Returns:
            List of identified gaps
        """
        if not timeline_data.get("has_dates"):
            return []

        gaps = []
        dates = timeline_data["dates"]
        
        # Find gaps larger than 7 days
        for i in range(len(dates) - 1):
            gap_days = (dates[i + 1] - dates[i]).days
            if gap_days > 7:
                gaps.append({
                    "start": dates[i],
                    "end": dates[i + 1],
                    "days": gap_days
                })

        return gaps

    def _format_empty(self) -> str:
        """Format output for no articles."""
        return f"""
╔════════════════════════════════════════════════════════════════╗
║                   ARTICLE COVERAGE INSPECTOR                   ║
╚════════════════════════════════════════════════════════════════╝

Question ID: {self.question_id}

STATUS: No Articles Collected
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

No articles have been collected yet for this question.

RECOMMENDATION:
→ Start evidence collection with web_search and article_collector
→ Search for articles covering the key events and time period
→ Aim for 5-10 diverse articles from different sources
"""

    def _format_error(self, error: str) -> str:
        """Format error message."""
        return f"""
╔════════════════════════════════════════════════════════════════╗
║                   ARTICLE COVERAGE INSPECTOR                   ║
╚════════════════════════════════════════════════════════════════╝

ERROR: {error}
"""

    def _format_visualization(
        self,
        articles: List[Article],
        timeline_data: Dict,
        source_data: Dict,
        gaps: List[Dict],
        resolution_date: datetime
    ) -> str:
        """Format the article analysis as visual text.

        Args:
            articles: List of articles
            timeline_data: Timeline statistics
            source_data: Source statistics
            gaps: Identified timeline gaps
            resolution_date: Question resolution date

        Returns:
            Formatted multi-section text
        """
        sections = []

        # Header
        sections.append("""
╔════════════════════════════════════════════════════════════════╗
║                   ARTICLE COVERAGE INSPECTOR                   ║
╚════════════════════════════════════════════════════════════════╝
""")

        # Overview
        sections.append(f"Question ID: {self.question_id}")
        sections.append(f"Total Articles: {len(articles)}")
        sections.append(f"Resolution Date: {resolution_date.strftime('%Y-%m-%d')}")
        sections.append("")

        # Timeline section
        if timeline_data.get("has_dates"):
            sections.append("TIMELINE DISTRIBUTION")
            sections.append("━" * 64)
            sections.append("")
            sections.append(f"  Date Range:  {timeline_data['earliest'].strftime('%Y-%m-%d')} → {resolution_date.strftime('%Y-%m-%d')}")
            sections.append(f"  Time Span:   {timeline_data['span_days']} days")
            sections.append("")

            # Monthly bar chart
            sections.append("  Articles by Month:")
            monthly = timeline_data['monthly']
            max_count = max(monthly.values()) if monthly else 1
            for month in sorted(monthly.keys()):
                count = monthly[month]
                bar_len = int((count / max_count) * 30)
                bar = "█" * bar_len
                sections.append(f"    {month}: {bar} ({count})")
            sections.append("")
        
        # Gaps section
        if gaps:
            sections.append("TIMELINE GAPS (>7 days)")
            sections.append("━" * 64)
            sections.append("")
            for gap in gaps[:5]:  # Show top 5 gaps
                sections.append(f"  ⚠ {gap['start'].strftime('%Y-%m-%d')} → {gap['end'].strftime('%Y-%m-%d')}")
                sections.append(f"     Gap: {gap['days']} days")
            sections.append("")
        
        # Source diversity
        sections.append("SOURCE DIVERSITY")
        sections.append("━" * 64)
        sections.append("")
        sections.append(f"  Unique Sources:  {source_data['unique_sources']}")
        sections.append(f"  Unique Domains:  {source_data['unique_domains']}")
        sections.append("")
        sections.append("  Top Sources:")
        for source, count in source_data['top_sources']:
            sections.append(f"    • {source}: {count} articles")
        sections.append("")
        
        # Coverage quality
        quality = self._calculate_quality(articles, timeline_data, source_data, gaps)
        sections.append("COVERAGE QUALITY")
        sections.append("━" * 64)
        sections.append("")
        sections.append(f"  Quality Score:  {quality['score']:.2f}/1.00")
        sections.append(f"  Volume:         {quality['volume_score']:.2f} ({len(articles)} articles)")
        sections.append(f"  Diversity:      {quality['diversity_score']:.2f} ({source_data['unique_sources']} sources)")
        sections.append(f"  Coverage:       {quality['coverage_score']:.2f} (gaps: {len(gaps)})")
        sections.append("")
        
        # Recommendation
        recommendation = self._get_recommendation(quality, gaps, source_data, timeline_data)
        sections.append("RECOMMENDATION")
        sections.append("━" * 64)
        sections.append(f"  {recommendation}")
        sections.append("")
        
        return "\n".join(sections)

    def _calculate_quality(
        self,
        articles: List[Article],
        timeline_data: Dict,
        source_data: Dict,
        gaps: List[Dict]
    ) -> Dict:
        """Calculate overall coverage quality score.

        Args:
            articles: List of articles
            timeline_data: Timeline statistics
            source_data: Source statistics
            gaps: Timeline gaps

        Returns:
            Quality metrics
        """
        # Volume score (5-10 articles = optimal)
        article_count = len(articles)
        if article_count >= 10:
            volume_score = 1.0
        elif article_count >= 5:
            volume_score = 0.5 + (article_count - 5) * 0.1
        else:
            volume_score = article_count * 0.1

        # Diversity score (3+ sources = good)
        unique_sources = source_data['unique_sources']
        diversity_score = min(unique_sources / 5.0, 1.0)

        # Coverage score (fewer gaps = better)
        if not timeline_data.get("has_dates"):
            coverage_score = 0.0
        else:
            gap_penalty = len(gaps) * 0.15
            coverage_score = max(0.0, 1.0 - gap_penalty)

        # Overall quality
        overall = (volume_score * 0.4 + diversity_score * 0.3 + coverage_score * 0.3)

        return {
            "score": overall,
            "volume_score": volume_score,
            "diversity_score": diversity_score,
            "coverage_score": coverage_score
        }

    def _get_recommendation(
        self,
        quality: Dict,
        gaps: List[Dict],
        source_data: Dict,
        timeline_data: Dict
    ) -> str:
        """Generate actionable recommendation.

        Args:
            quality: Quality metrics
            gaps: Timeline gaps
            source_data: Source statistics
            timeline_data: Timeline statistics

        Returns:
            Recommendation string
        """
        if quality['score'] >= 0.8:
            return "✓ Excellent coverage! You have sufficient diverse articles with good timeline coverage."
        
        issues = []
        
        if quality['volume_score'] < 0.5:
            issues.append("Need more articles (aim for 5-10)")
        
        if quality['diversity_score'] < 0.6:
            issues.append(f"Low source diversity (only {source_data['unique_sources']} sources)")
        
        if gaps:
            top_gap = max(gaps, key=lambda g: g['days'])
            issues.append(f"Large time gap: {top_gap['start'].strftime('%Y-%m-%d')} to {top_gap['end'].strftime('%Y-%m-%d')}")
        
        if issues:
            return "⚠ " + " | ".join(issues) + "\n  → Search for more articles to fill gaps and increase diversity"
        
        return "Good coverage, but could be improved with a few more diverse sources."
