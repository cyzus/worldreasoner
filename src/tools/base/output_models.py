"""Pydantic output models for tools.

This module defines Pydantic models for tool outputs, which can be converted
to JSON schemas for smolagents output_schema attribute using schema_helper.

These models serve as:
1. Documentation of expected tool output structure
2. Source for output_schema generation
3. Optional runtime validation (if needed)
"""

import json
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

# Make all Pydantic output models JSON-serializable with the standard json module.
# This allows CodeAgent-generated code to call json.dumps(tool_result) without errors.
_original_default = json.JSONEncoder.default


def _pydantic_aware_default(self, obj):
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    return _original_default(self, obj)


json.JSONEncoder.default = _pydantic_aware_default


class OutputModelBase(BaseModel):
    """Base model for tool outputs with dict-like compatibility helpers."""

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def keys(self):
        return self.model_dump().keys()

    def items(self):
        return self.model_dump().items()

    def values(self):
        return self.model_dump().values()


# =============================================================================
# Article Tools
# =============================================================================


class ArticleOutput(OutputModelBase):
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


class ArticleRetrievalOutput(OutputModelBase):
    """Output model for ArticleRetrievalTool."""

    id: str = Field(description="Article ID")
    title: str = Field(description="Article title")
    url: str = Field(description="Article URL")
    content: str = Field(description="Full article content")
    source: Optional[str] = Field(default=None, description="Source name")
    published_date: Optional[str] = Field(default=None, description="Publication date")
    word_count: Optional[int] = Field(default=None, description="Word count")


class ArticleListItem(OutputModelBase):
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


class QuestionArticlesOutput(OutputModelBase):
    """Output model for QuestionArticlesTool."""

    articles: List[ArticleListItem] = Field(description="List of articles")
    total: int = Field(description="Total number of articles")
    limit: int = Field(description="Page size limit")
    offset: int = Field(description="Pagination offset")


# =============================================================================
# Event Tools
# =============================================================================


class EventOutput(OutputModelBase):
    """Output model for EventIdentifierTool."""

    id: str = Field(description="Event ID")
    alias: Optional[str] = Field(
        default=None,
        description="Short semantic label for the event (e.g., E1:KhameneiDeath)",
    )
    title: str = Field(description="Event title")
    domain: str = Field(description="Event domain (tech, finance, etc.)")
    status: str = Field(description="Processing status (created/updated/existing)")
    occurred_date: Optional[str] = Field(
        default=None, description="When event occurred"
    )
    event_type: Optional[str] = Field(default=None, description="Type of event")
    warnings: Optional[List[str]] = Field(
        default=None,
        description="Validation warnings about date accuracy or other issues. Review these and correct events if needed.",
    )
    actual_outcome_event_id: Optional[str] = Field(
        default=None,
        description="ID of the actual ground-truth outcome event (if known/available)",
    )

class EventDetailsOutput(OutputModelBase):
    """Output model for EventDetailsTool."""

    event: Dict[str, Any] = Field(description="Full event details dictionary")
    linked_articles: List[Dict[str, Any]] = Field(
        default_factory=list, description="Linked article content"
    )
    summary: str = Field(description="Brief summary of event and articles")


class OutcomeEventItem(OutputModelBase):
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


class RegularEventItem(OutputModelBase):
    """Single regular event in list response."""

    id: str = Field(description="Event ID")
    title: str = Field(description="Event title")
    occurred_date: Optional[str] = Field(default=None, description="When occurred")
    predicted_date: Optional[str] = Field(default=None, description="When predicted")


class QuestionEventsOutput(OutputModelBase):
    """Output model for QuestionEventsTool."""

    outcome_events: List[OutcomeEventItem] = Field(description="Outcome events list")
    regular_events: List[RegularEventItem] = Field(description="Regular events list")
    total: int = Field(description="Total events count")


class OutcomeImpactOutput(OutputModelBase):
    """Output model for RecordOutcomeImpactTool."""

    status: str = Field(description="Operation status (recorded/error)")
    impact_id: str = Field(description="ID of created impact record")
    error: Optional[str] = Field(
        default=None, description="Error message if status is error"
    )


# =============================================================================
# Hypothesis / Causal Reasoner Tools
# =============================================================================


class HypothesisOutput(OutputModelBase):
    """Output model for CausalReasonerTool."""

    status: str = Field(description="Operation status (created/updated/error)")
    hypothesis_id: str = Field(description="ID of created hypothesis")
    source_alias: Optional[str] = Field(
        default=None, description="Alias of the source event"
    )
    target_alias: Optional[str] = Field(
        default=None, description="Alias of the target event"
    )
    relation: str = Field(description="Formatted relation string")
    strength: float = Field(description="Causal strength 0.0-1.0")
    confidence: float = Field(description="Confidence level 0.0-1.0")
    evidence_count: int = Field(default=0, description="Number of evidence articles")
    outcome_connected: Optional[bool] = Field(
        default=None, description="Whether the target event is the actual outcome"
    )
    error: Optional[str] = Field(
        default=None, description="Error message if status is error"
    )

class ForecastHypothesisOutput(OutputModelBase):
    """Output model for ForecastCausalReasonerTool."""

    status: str = Field(description="Operation status (created)")
    hypothesis_id: str = Field(description="ID of created hypothesis")
    relation: str = Field(description="Formatted relation string")
    strength: float = Field(description="Causal strength 0.0-1.0")
    confidence: float = Field(description="Confidence level 0.0-1.0")


# =============================================================================
# Graph Builder Tools
# =============================================================================


class SaveExplanationOutput(OutputModelBase):
    """Output model for SaveExplanationTool."""

    status: str = Field(description="Operation status")
    question_id: str = Field(description="ID of the question")
    message: str = Field(description="Status message")
    article_references_found: int = Field(
        default=0, description="Number of article ID references detected in the explanation"
    )
    warnings: Optional[List[str]] = Field(
        default=None,
        description="Validation warnings — explanation was saved but may be weak. Address these before finishing.",
    )


class SubgraphOutput(OutputModelBase):
    """Output model for ProposeSubgraphTool."""

    status: str = Field(description="Operation status")
    events_created: int = Field(description="Number of events successfully created")
    edges_created: int = Field(
        description="Number of causal edges successfully created"
    )
    failed_items: List[Dict[str, Any]] = Field(
        default_factory=list, description="Items that failed to create with reasons"
    )
    alias_map: Dict[str, str] = Field(
        default_factory=dict, description="Map of aliases to generated IDs"
    )


# =============================================================================
# Forecast Event Tools
# =============================================================================


class ForecastEventOutput(OutputModelBase):
    """Output model for ForecastEventIdentifierTool."""

    status: str = Field(description="Operation status (created/reused)")
    event: Dict[str, Any] = Field(description="Event object with id, title, domain")


# =============================================================================
# MCP Forecasting API Outputs
# =============================================================================


class ErrorResponse(OutputModelBase):
    """Standard error payload for MCP tool responses."""

    error: str = Field(description="Error message")


class QuestionInfo(OutputModelBase):
    """Question details for forecasting context."""

    id: str
    question_text: str
    question_type: str
    domain: str
    difficulty: Optional[int] = None
    options: Optional[List[str]] = None
    quantity_unit: Optional[str] = None


class TemporalContextInfo(OutputModelBase):
    """Temporal setup details for a forecast session."""

    knowledge_cutoff_date: Optional[str] = None
    today_date: str = Field(alias="today's date")
    explanation: str


class GetQuestionResponse(OutputModelBase):
    """Response payload for get_question MCP tool."""

    question: QuestionInfo
    temporal_context: TemporalContextInfo
    instructions: str


class SearchArticleItem(OutputModelBase):
    """Single article summary item in temporal search responses."""

    id: str
    title: str
    url: Optional[str] = None
    source: Optional[str] = None
    domain: str
    published_date: str
    word_count: Optional[int] = None
    excerpt: str


class TemporalSearchArticlesResponse(OutputModelBase):
    """Response payload for temporal_search_articles MCP tool."""

    query: str
    simulated_date: str
    note: str
    count: int
    articles: List[SearchArticleItem]


class FetchArticleResponse(OutputModelBase):
    """Response payload for fetch_article MCP tool."""

    id: str
    title: str
    url: Optional[str] = None
    source: Optional[str] = None
    domain: str
    published_date: str
    author: Optional[str] = None
    word_count: Optional[int] = None
    tags: Optional[List[str]] = None
    content: str
    event_ids: Optional[List[str]] = None


class SubmitForecastResponse(OutputModelBase):
    """Response payload for submit_forecast MCP tool."""

    forecast_id: str
    question_id: str
    prediction: Any
    confidence: float
    simulated_date: str
    submitted_at: str
    status: str
    graph_links: Dict[str, int]
    note: str


# =============================================================================
# Question Tools
# =============================================================================


class QuestionOutput(OutputModelBase):
    """Output model for QuestionGeneratorTool."""

    id: str = Field(description="Question ID")
    question_text: str = Field(description="Question text")
    status: str = Field(description="Question status")


class QualityScore(OutputModelBase):
    """Quality score details."""

    score: float = Field(description="Score value 0.0-1.0")
    feedback: str = Field(description="Feedback message")


class QuestionQualityOutput(OutputModelBase):
    """Output model for QuestionQualityScorerTool."""

    scores: List[Dict[str, Any]] = Field(
        description="List of quality scores per question"
    )
    overall_quality: str = Field(description="Overall quality assessment")


# =============================================================================
# Web Tools
# =============================================================================


class WebFetchOutput(OutputModelBase):
    """Output model for WebFetchTool."""

    url: str = Field(description="Fetched URL")
    content: str = Field(description="Page content")
    title: Optional[str] = Field(default=None, description="Page title")
    links: Optional[List[str]] = Field(default=None, description="Extracted links")
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="Additional metadata"
    )
    success: bool = Field(default=True, description="Fetch success status")
    error: Optional[str] = Field(default=None, description="Error message")


class RssFeedItem(OutputModelBase):
    """Single item from RSS feed."""

    title: str = Field(description="Item title")
    link: str = Field(description="Item URL")
    published: str = Field(description="Publication date ISO")
    summary: str = Field(description="Item summary/content")


class RssFetchOutput(OutputModelBase):
    """Output model for RssFetchTool."""

    feed_url: str = Field(description="Feed URL")
    total_items: int = Field(description="Number of items returned")
    items: List[RssFeedItem] = Field(description="Feed items")
