"""Pydantic output models for tools.

This module defines Pydantic models for tool outputs, which can be converted
to JSON schemas for smolagents output_schema attribute using schema_helper.

These models serve as:
1. Documentation of expected tool output structure
2. Source for output_schema generation
3. Optional runtime validation (if needed)
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


# =============================================================================
# Article Tools
# =============================================================================


class ArticleOutput(BaseModel):
    """Output model for ArticleCollectorTool."""

    id: str = Field(description="Article ID")
    title: str = Field(description="Article title")
    url: str = Field(description="Article URL")
    source: Optional[str] = Field(default=None, description="Source name")
    status: str = Field(description="Processing status (created/updated/existing)")
    word_count: Optional[int] = Field(default=None, description="Word count")
    published_date: Optional[str] = Field(
        default=None, description="Publication date ISO"
    )


class ArticleRetrievalOutput(BaseModel):
    """Output model for ArticleRetrievalTool."""

    id: str = Field(description="Article ID")
    title: str = Field(description="Article title")
    url: str = Field(description="Article URL")
    content: str = Field(description="Full article content")
    source: Optional[str] = Field(default=None, description="Source name")
    published_date: Optional[str] = Field(default=None, description="Publication date")
    word_count: Optional[int] = Field(default=None, description="Word count")


class ArticleListItem(BaseModel):
    """Single article in a list response."""

    id: str = Field(description="Article ID")
    title: str = Field(description="Article title")
    source: Optional[str] = Field(default=None, description="Source name")
    url: Optional[str] = Field(default=None, description="Article URL")
    published_date: Optional[str] = Field(default=None, description="Publication date")
    content_preview: Optional[str] = Field(
        default=None, description="Preview of article content"
    )
    word_count: Optional[int] = Field(default=None, description="Word count")


class QuestionArticlesOutput(BaseModel):
    """Output model for QuestionArticlesTool."""

    articles: List[ArticleListItem] = Field(description="List of articles")
    total: int = Field(description="Total number of articles")
    limit: int = Field(description="Page size limit")
    offset: int = Field(description="Pagination offset")


# =============================================================================
# Event Tools
# =============================================================================


class EventOutput(BaseModel):
    """Output model for EventIdentifierTool."""

    id: str = Field(description="Event ID")
    title: str = Field(description="Event title")
    domain: str = Field(description="Event domain (tech, finance, etc.)")
    status: str = Field(description="Processing status (created/updated/existing)")
    occurred_date: Optional[str] = Field(default=None, description="When event occurred")
    event_type: Optional[str] = Field(default=None, description="Type of event")


class EventDetailsOutput(BaseModel):
    """Output model for EventDetailsTool."""

    event: Dict[str, Any] = Field(description="Full event details dictionary")
    linked_articles: List[Dict[str, Any]] = Field(
        default_factory=list, description="Linked article content"
    )
    summary: str = Field(description="Brief summary of event and articles")


class OutcomeEventItem(BaseModel):
    """Single outcome event in list response."""

    id: str = Field(description="Event ID")
    title: str = Field(description="Event title")
    occurred_date: Optional[str] = Field(default=None, description="When occurred")
    predicted_date: Optional[str] = Field(default=None, description="When predicted")
    outcome_scenario: Optional[str] = Field(
        default=None, description="Outcome scenario label"
    )
    is_actual_outcome: bool = Field(
        default=False, description="Whether this is the actual outcome"
    )


class RegularEventItem(BaseModel):
    """Single regular event in list response."""

    id: str = Field(description="Event ID")
    title: str = Field(description="Event title")
    occurred_date: Optional[str] = Field(default=None, description="When occurred")
    predicted_date: Optional[str] = Field(default=None, description="When predicted")


class QuestionEventsOutput(BaseModel):
    """Output model for QuestionEventsTool."""

    outcome_events: List[OutcomeEventItem] = Field(description="Outcome events list")
    regular_events: List[RegularEventItem] = Field(description="Regular events list")
    total: int = Field(description="Total events count")


# =============================================================================
# Hypothesis / Causal Reasoner Tools
# =============================================================================


class HypothesisOutput(BaseModel):
    """Output model for CausalReasonerTool."""

    status: str = Field(description="Operation status (created/updated)")
    hypothesis_id: str = Field(description="ID of created hypothesis")
    relation: str = Field(description="Formatted relation string")
    strength: float = Field(description="Causal strength 0.0-1.0")
    confidence: float = Field(description="Confidence level 0.0-1.0")
    evidence_count: int = Field(default=0, description="Number of evidence articles")


class ForecastHypothesisOutput(BaseModel):
    """Output model for ForecastCausalReasonerTool."""

    status: str = Field(description="Operation status (created)")
    hypothesis_id: str = Field(description="ID of created hypothesis")
    relation: str = Field(description="Formatted relation string")
    strength: float = Field(description="Causal strength 0.0-1.0")
    confidence: float = Field(description="Confidence level 0.0-1.0")


# =============================================================================
# Forecast Event Tools
# =============================================================================


class ForecastEventOutput(BaseModel):
    """Output model for ForecastEventIdentifierTool."""

    status: str = Field(description="Operation status (created/reused)")
    event: Dict[str, Any] = Field(description="Event object with id, title, domain")


# =============================================================================
# Question Tools
# =============================================================================


class QuestionOutput(BaseModel):
    """Output model for QuestionGeneratorTool."""

    id: str = Field(description="Question ID")
    question_text: str = Field(description="Question text")
    status: str = Field(description="Question status")


class QualityScore(BaseModel):
    """Quality score details."""

    score: float = Field(description="Score value 0.0-1.0")
    feedback: str = Field(description="Feedback message")


class QuestionQualityOutput(BaseModel):
    """Output model for QuestionQualityScorerTool."""

    scores: List[Dict[str, Any]] = Field(description="List of quality scores per question")
    overall_quality: str = Field(description="Overall quality assessment")


# =============================================================================
# Web Tools
# =============================================================================


class WebFetchOutput(BaseModel):
    """Output model for WebFetchTool."""

    url: str = Field(description="Fetched URL")
    content: str = Field(description="Page content")
    title: Optional[str] = Field(default=None, description="Page title")
    links: Optional[List[str]] = Field(default=None, description="Extracted links")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional metadata")
    success: bool = Field(default=True, description="Fetch success status")
    error: Optional[str] = Field(default=None, description="Error message")


class RssFeedItem(BaseModel):
    """Single item from RSS feed."""

    title: str = Field(description="Item title")
    link: str = Field(description="Item URL")
    published: str = Field(description="Publication date ISO")
    summary: str = Field(description="Item summary/content")


class RssFetchOutput(BaseModel):
    """Output model for RssFetchTool."""

    feed_url: str = Field(description="Feed URL")
    total_items: int = Field(description="Number of items returned")
    items: List[RssFeedItem] = Field(description="Feed items")
