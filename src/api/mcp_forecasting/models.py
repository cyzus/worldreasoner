"""Pydantic response models for MCP forecasting tools."""

from typing import Any, Optional

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Standard error payload for MCP tool responses."""

    error: str = Field(description="Error message")


class QuestionInfo(BaseModel):
    id: str
    question_text: str
    question_type: str
    domain: str
    difficulty: Optional[int] = None
    options: Optional[list[str]] = None
    quantity_unit: Optional[str] = None


class TemporalContextInfo(BaseModel):
    knowledge_cutoff_date: Optional[str] = None
    today_date: str = Field(alias="today's date")
    explanation: str


class GetQuestionResponse(BaseModel):
    question: QuestionInfo
    temporal_context: TemporalContextInfo
    instructions: str


class SearchArticleItem(BaseModel):
    id: str
    title: str
    url: Optional[str] = None
    source: Optional[str] = None
    domain: str
    published_date: str
    word_count: Optional[int] = None
    excerpt: str


class TemporalSearchArticlesResponse(BaseModel):
    query: str
    simulated_date: str
    note: str
    count: int
    articles: list[SearchArticleItem]


class FetchArticleResponse(BaseModel):
    id: str
    title: str
    url: Optional[str] = None
    source: Optional[str] = None
    domain: str
    published_date: str
    author: Optional[str] = None
    word_count: Optional[int] = None
    tags: Optional[list[str]] = None
    content: str
    event_ids: Optional[list[str]] = None


class SubmitForecastResponse(BaseModel):
    forecast_id: str
    question_id: str
    prediction: Any
    confidence: float
    simulated_date: str
    submitted_at: str
    status: str
    graph_links: dict[str, int]
    note: str
