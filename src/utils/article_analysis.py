"""Shared utilities for article analysis - timeline, coverage, and quality metrics.

These utilities can be used by both backend tools and frontend API endpoints
to analyze article collections.
"""

from typing import List, Dict
from collections import defaultdict
from datetime import datetime

from src.domain.models import Article


def analyze_timeline(articles: List[Article], resolution_date: datetime) -> Dict:
    """Analyze temporal distribution of articles.

    Args:
        articles: List of articles
        resolution_date: Question resolution date (coverage endpoint)

    Returns:
        Timeline statistics including:
        - has_dates: Whether articles have date information
        - earliest: Earliest article date
        - resolution_date: Question resolution date
        - span_days: Days between earliest and resolution
        - monthly: Monthly article counts
        - dates: Sorted list of all article dates
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


def analyze_sources(articles: List[Article]) -> Dict:
    """Analyze source diversity.

    Args:
        articles: List of articles

    Returns:
        Source statistics including:
        - unique_sources: Number of unique sources
        - unique_domains: Number of unique domains
        - source_counts: Count per source
        - top_sources: Top 5 sources by article count
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


def identify_gaps(timeline_data: Dict, min_gap_days: int = 7) -> List[Dict]:
    """Identify significant time gaps in coverage.

    Args:
        timeline_data: Timeline analysis data from analyze_timeline()
        min_gap_days: Minimum gap size in days to report (default: 7)

    Returns:
        List of identified gaps with start, end, and duration in days
    """
    if not timeline_data.get("has_dates"):
        return []

    gaps = []
    dates = timeline_data["dates"]

    # Find gaps larger than min_gap_days
    for i in range(len(dates) - 1):
        gap_days = (dates[i + 1] - dates[i]).days
        if gap_days > min_gap_days:
            gaps.append({
                "start": dates[i],
                "end": dates[i + 1],
                "days": gap_days
            })

    return gaps


def calculate_quality(
    articles: List[Article],
    timeline_data: Dict,
    source_data: Dict,
    gaps: List[Dict]
) -> Dict:
    """Calculate overall coverage quality score.

    Args:
        articles: List of articles
        timeline_data: Timeline statistics from analyze_timeline()
        source_data: Source statistics from analyze_sources()
        gaps: Timeline gaps from identify_gaps()

    Returns:
        Quality metrics including:
        - score: Overall quality score (0-1)
        - volume_score: Score based on article count (0-1)
        - diversity_score: Score based on source diversity (0-1)
        - coverage_score: Score based on timeline gaps (0-1)
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

    # Overall quality (weighted average)
    overall = (volume_score * 0.4 + diversity_score * 0.3 + coverage_score * 0.3)

    return {
        "score": overall,
        "volume_score": volume_score,
        "diversity_score": diversity_score,
        "coverage_score": coverage_score
    }


def get_recommendation(
    quality: Dict,
    gaps: List[Dict],
    source_data: Dict,
    timeline_data: Dict
) -> str:
    """Generate actionable recommendation based on coverage analysis.

    Args:
        quality: Quality metrics from calculate_quality()
        gaps: Timeline gaps from identify_gaps()
        source_data: Source statistics from analyze_sources()
        timeline_data: Timeline statistics from analyze_timeline()

    Returns:
        Human-readable recommendation string
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


def calculate_simple_quality(articles: List[Article]) -> Dict:
    """Calculate simple article quality score based on count and source diversity.

    This is a lightweight quality calculation used by the pipeline for quick
    quality assessment without timeline analysis.

    Args:
        articles: List of articles to analyze

    Returns:
        Dictionary with:
        - score: Overall quality score (0-1)
        - article_count: Number of articles
        - unique_sources: Number of unique sources
    """
    if not articles:
        return {
            "score": 0.0,
            "article_count": 0,
            "unique_sources": 0
        }

    article_count = len(articles)
    sources = {
        getattr(article, "source", "unknown")
        for article in articles
    }
    unique_sources = len(sources)

    # Simple quality score based on count and source diversity
    # Coverage factor: normalized by 50 articles (50+ = full score)
    coverage_factor = min(article_count / 50.0, 1.0)
    # Source diversity: normalized by 10 sources (10+ = full score)
    source_diversity_factor = min(unique_sources / 10.0, 1.0)

    # Weighted combination (60% coverage, 40% diversity)
    quality_score = max(0.0, min(
        (coverage_factor * 0.6) + (source_diversity_factor * 0.4),
        1.0
    ))

    return {
        "score": quality_score,
        "article_count": article_count,
        "unique_sources": unique_sources
    }


def analyze_article_coverage(articles: List[Article], resolution_date: datetime) -> Dict:
    """Perform complete article coverage analysis.

    Convenience function that runs all analysis steps and returns complete results.
    Useful for API endpoints that need full analysis in one call.

    Args:
        articles: List of articles to analyze
        resolution_date: Question resolution date

    Returns:
        Complete analysis including timeline, sources, gaps, quality, and recommendations
    """
    timeline_data = analyze_timeline(articles, resolution_date)
    source_data = analyze_sources(articles)
    gaps = identify_gaps(timeline_data)
    quality = calculate_quality(articles, timeline_data, source_data, gaps)
    recommendation = get_recommendation(quality, gaps, source_data, timeline_data)

    return {
        "article_count": len(articles),
        "timeline": timeline_data,
        "sources": source_data,
        "gaps": gaps,
        "quality": quality,
        "recommendation": recommendation
    }
