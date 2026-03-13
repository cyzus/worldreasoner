"""Shared utilities for article analysis - timeline, coverage, and quality metrics.

These utilities can be used by both backend tools and frontend API endpoints
to analyze article collections.
"""

from typing import List, Dict
from collections import defaultdict
from datetime import datetime

from src.domain.models import Article


def analyze_timeline(
    articles: List[Article], resolution_date: datetime, coverage_start: datetime = None
) -> Dict:
    """Analyze temporal distribution of articles.

    Args:
        articles: List of articles
        resolution_date: Question resolution date (coverage endpoint)
        coverage_start: Optional expected start of coverage (e.g., estimated_start_time)

    Returns:
        Timeline statistics including:
        - has_dates: Whether articles have date information
        - earliest: Earliest article date
        - resolution_date: Question resolution date
        - span_days: Days between earliest article and resolution
        - expected_span_days: Days between coverage_start and resolution (if coverage_start provided)
        - monthly: Monthly article counts
        - dates: Sorted list of all article dates
    """
    dates = [a.published_date for a in articles if a.published_date]

    result = {"has_dates": False, "resolution_date": resolution_date}

    # Calculate expected span if coverage_start is provided
    if coverage_start:
        result["expected_span_days"] = (resolution_date - coverage_start).days

    if not dates:
        return result

    dates.sort()
    earliest = dates[0]
    span_days = (resolution_date - earliest).days

    # Group by month for visualization
    monthly = defaultdict(int)
    for date in dates:
        month_key = date.strftime("%Y-%m")
        monthly[month_key] += 1

    result.update(
        {
            "has_dates": True,
            "earliest": earliest,
            "span_days": span_days,
            "monthly": dict(monthly),
            "dates": dates,
        }
    )

    return result


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
        "top_sources": sorted(sources.items(), key=lambda x: x[1], reverse=True)[:5],
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
            gaps.append({"start": dates[i], "end": dates[i + 1], "days": gap_days})

    return gaps


def calculate_volume_score(article_count: int, min_articles: int = 20) -> float:
    """Calculate quality score based on article count.

    Args:
        article_count: Number of articles
        min_articles: Target minimum article count (from EvidenceSatisfactionConfig)

    Returns:
        Volume score (0-1), saturating at min_articles
    """
    if article_count >= min_articles:
        return 1.0
    half = min_articles // 2
    if article_count >= half:
        return 0.5 + (article_count - half) * (0.5 / half)
    return article_count * (0.5 / half)


def calculate_diversity_score(unique_sources: int) -> float:
    """Calculate quality score based on source diversity.

    Uses exponential curve that heavily penalizes 1-2 sources.

    Args:
        unique_sources: Number of unique sources

    Returns:
        Diversity score (0-1)
    """
    if unique_sources == 1:
        return 0.1  # Single source = very poor
    elif unique_sources == 2:
        return 0.3
    elif unique_sources == 3:
        return 0.5
    elif unique_sources == 4:
        return 0.7
    else:
        return min(0.7 + (unique_sources - 4) * 0.075, 1.0)


def calculate_gap_severity(gaps: List[Dict], timeline_span_days: int) -> float:
    """Calculate gap severity considering both absolute and relative size.

    Args:
        gaps: List of timeline gaps from identify_gaps()
        timeline_span_days: Total span of the coverage window in days

    Returns:
        Total gap severity penalty (0-1)
    """
    if not gaps or timeline_span_days <= 0:
        return 0.0

    total_penalty = 0.0
    for gap in gaps:
        gap_days = gap["days"]

        # Absolute penalty: exponential scaling for larger gaps
        # 7-14 days: mild, 15-30 days: moderate, 30+ days: severe
        if gap_days <= 14:
            absolute_penalty = 0.05
        elif gap_days <= 30:
            absolute_penalty = 0.10
        elif gap_days <= 60:
            absolute_penalty = 0.20
        else:
            absolute_penalty = 0.30

        # Relative penalty: gap as % of total timeline
        relative_penalty = min(gap_days / timeline_span_days * 0.5, 0.3)

        # Combined penalty (take maximum to penalize both large absolute and relative gaps)
        total_penalty += max(absolute_penalty, relative_penalty)

    return min(total_penalty, 1.0)  # Cap at 1.0


def calculate_early_gap_penalty(
    earliest_article: datetime, coverage_start: datetime, timeline_span_days: int
) -> float:
    """Penalize missing coverage at start of window.

    Args:
        earliest_article: Date of earliest article
        coverage_start: Expected start of coverage window
        timeline_span_days: Total span of the coverage window in days

    Returns:
        Early gap penalty (0-0.25)
    """
    if earliest_article <= coverage_start:
        return 0.0

    early_gap_days = (earliest_article - coverage_start).days

    # Absolute penalty for early gap
    if early_gap_days <= 7:
        return 0.05
    elif early_gap_days <= 30:
        return 0.15
    else:
        return 0.25


def calculate_distribution_score(timeline_data: Dict) -> float:
    """Score based on how evenly articles are distributed across timeline.

    Uses coefficient of variation to measure distribution evenness.

    Args:
        timeline_data: Timeline statistics from analyze_timeline()

    Returns:
        Distribution score (0-1), where 1.0 is perfectly even distribution
    """
    if not timeline_data.get("has_dates") or not timeline_data.get("monthly"):
        return 0.0

    monthly_counts = list(timeline_data["monthly"].values())
    if len(monthly_counts) <= 1:
        return 0.5  # Only one month has articles

    # Calculate coefficient of variation (lower = more even distribution)
    mean = sum(monthly_counts) / len(monthly_counts)
    if mean == 0:
        return 0.0

    variance = sum((x - mean) ** 2 for x in monthly_counts) / len(monthly_counts)
    std_dev = variance**0.5
    cv = std_dev / mean

    # Convert CV to score (0 = perfect uniformity, high CV = clustered)
    # CV > 1.0 is very uneven, CV < 0.5 is fairly even
    return max(0.0, min(1.0 - (cv / 2.0), 1.0))


def calculate_quality(
    articles: List[Article],
    timeline_data: Dict,
    source_data: Dict,
    gaps: List[Dict],
    coverage_start: datetime = None,
    min_articles: int = 20,
) -> Dict:
    """Calculate overall coverage quality score.

    Uses improved heuristics that consider gap severity, early coverage gaps,
    distribution evenness, and stricter source diversity requirements.

    Args:
        articles: List of articles
        timeline_data: Timeline statistics from analyze_timeline()
        source_data: Source statistics from analyze_sources()
        gaps: Timeline gaps from identify_gaps()
        coverage_start: Expected start of coverage window (e.g., estimated_start_time)

    Returns:
        Quality metrics including:
        - score: Overall quality score (0-1)
        - volume_score: Score based on article count (0-1)
        - diversity_score: Score based on source diversity (0-1)
        - coverage_score: Score based on timeline gaps and distribution (0-1)
        - distribution_score: Score based on temporal distribution evenness (0-1)
        - gap_severity: Total gap severity penalty (0-1)
    """
    # Volume score — saturates at min_articles
    volume_score = calculate_volume_score(len(articles), min_articles=min_articles)

    # Improved diversity score (stricter penalties for 1-3 sources)
    diversity_score = calculate_diversity_score(source_data["unique_sources"])

    # Coverage score with gap severity and distribution
    if timeline_data.get("has_dates"):
        # Use expected span (coverage_start to resolution) if available,
        # otherwise fall back to article span (earliest to resolution)
        timeline_span = timeline_data.get(
            "expected_span_days", timeline_data["span_days"]
        )

        # Gap severity penalty (considers both absolute and relative gap sizes)
        # Now calculated relative to the EXPECTED coverage window, not just article span
        gap_severity = calculate_gap_severity(gaps, timeline_span)

        # Attenuate gap severity when articles span most of the expected window.
        # Full span coverage reduces severity by up to 40%; floor of 0.6 ensures
        # gaps are never fully ignored.
        if timeline_span > 0 and gap_severity > 0:
            span_coverage = min(timeline_data["span_days"] / timeline_span, 1.0)
            gap_severity *= max(1.0 - span_coverage * 0.4, 0.6)

        # Early coverage gap penalty
        early_gap_penalty = 0.0
        if coverage_start and timeline_data.get("earliest"):
            early_gap_penalty = calculate_early_gap_penalty(
                timeline_data["earliest"], coverage_start, timeline_span
            )

        # Distribution score (how evenly articles are spread)
        distribution_score = calculate_distribution_score(timeline_data)

        # Combined coverage score
        # Start at 1.0, apply penalties, blend with distribution score
        coverage_score = max(0.0, 1.0 - gap_severity - early_gap_penalty)
        coverage_score = (coverage_score * 0.7) + (distribution_score * 0.3)
    else:
        coverage_score = 0.0
        distribution_score = 0.0
        gap_severity = 0.0

    # Overall quality - adjusted weights (Volume: 35%, Diversity: 25%, Coverage: 40%)
    overall = volume_score * 0.35 + diversity_score * 0.25 + coverage_score * 0.40

    return {
        "score": overall,
        "volume_score": volume_score,
        "diversity_score": diversity_score,
        "coverage_score": coverage_score,
        "distribution_score": distribution_score,
        "gap_severity": gap_severity,
    }


def get_recommendation(
    quality: Dict,
    gaps: List[Dict],
    source_data: Dict,
    timeline_data: Dict,
    min_articles: int = 20,
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
    if quality["score"] >= 0.8:
        return "✓ Excellent coverage! You have sufficient diverse articles with good timeline coverage."

    issues = []

    if quality["volume_score"] < 0.5:
        issues.append(f"Need more articles (aim for {min_articles})")

    if quality["diversity_score"] < 0.6:
        issues.append(
            f"Low source diversity (only {source_data['unique_sources']} sources)"
        )

    if gaps:
        top_gap = max(gaps, key=lambda g: g["days"])
        issues.append(
            f"Large time gap: {top_gap['start'].strftime('%Y-%m-%d')} to {top_gap['end'].strftime('%Y-%m-%d')}"
        )

    if issues:
        return (
            "⚠ "
            + " | ".join(issues)
            + "\n  → Search for more articles to fill gaps and increase diversity"
        )

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
        return {"score": 0.0, "article_count": 0, "unique_sources": 0}

    article_count = len(articles)
    sources = {getattr(article, "source", "unknown") for article in articles}
    unique_sources = len(sources)

    # Simple quality score based on count and source diversity
    # Coverage factor: normalized by 50 articles (50+ = full score)
    coverage_factor = min(article_count / 50.0, 1.0)
    # Source diversity: normalized by 10 sources (10+ = full score)
    source_diversity_factor = min(unique_sources / 10.0, 1.0)

    # Weighted combination (60% coverage, 40% diversity)
    quality_score = max(
        0.0, min((coverage_factor * 0.6) + (source_diversity_factor * 0.4), 1.0)
    )

    return {
        "score": quality_score,
        "article_count": article_count,
        "unique_sources": unique_sources,
    }


def analyze_article_coverage(
    articles: List[Article], resolution_date: datetime, coverage_start: datetime = None
) -> Dict:
    """Perform complete article coverage analysis.

    Convenience function that runs all analysis steps and returns complete results.
    Useful for API endpoints that need full analysis in one call.

    Args:
        articles: List of articles to analyze
        resolution_date: Question resolution date
        coverage_start: Optional expected start of coverage window for early gap penalty

    Returns:
        Complete analysis including timeline, sources, gaps, quality, and recommendations
    """
    timeline_data = analyze_timeline(
        articles, resolution_date, coverage_start=coverage_start
    )
    source_data = analyze_sources(articles)
    gaps = identify_gaps(timeline_data)
    quality = calculate_quality(
        articles, timeline_data, source_data, gaps, coverage_start
    )
    recommendation = get_recommendation(quality, gaps, source_data, timeline_data)

    return {
        "article_count": len(articles),
        "timeline": timeline_data,
        "sources": source_data,
        "gaps": gaps,
        "quality": quality,
        "recommendation": recommendation,
    }
