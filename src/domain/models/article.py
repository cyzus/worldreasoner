"""Article data model."""

from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field, ConfigDict
from ...core.database import register_model
from .domain import Domain


@register_model(
    "articles",
    indexes=["domain", "source", "published_date", "collected_for_question_id"],
)
class Article(BaseModel):
    """News article with temporal and causal metadata.

    This is the fundamental unit of information in the system.
    Articles can be real (scraped from news sources) or synthetic
    (generated for controlled testing).
    """

    # Core identification
    id: str = Field(..., description="Unique article identifier")
    title: str = Field(..., min_length=10, max_length=500)
    content: str = Field(..., min_length=100, description="Full article text")
    url: Optional[str] = Field(None, description="Source URL of the article")

    # Source information
    source: str = Field(..., description="Publication source name")
    author: Optional[str] = None
    published_date: datetime = Field(..., description="Publication timestamp")

    # Classification
    domain: Domain = Field(..., description="Primary domain")
    tags: List[str] = Field(default_factory=list, description="Topic tags")

    # Metadata
    is_synthetic: bool = Field(
        default=False, description="Whether article is generated"
    )
    language: str = Field(default="en", description="ISO 639-1 language code")

    # Event references
    event_ids: List[str] = Field(
        default_factory=list,
        description="IDs of events discussed or documented in this article",
    )

    # Provenance tracking (for evidence pipeline)
    collected_for_question_id: Optional[str] = Field(
        None,
        description="Question ID this article was collected for during evidence pipeline (None if pre-existing)",
    )

    # Computed fields
    word_count: Optional[int] = Field(None, description="Number of words in content")
    reading_time_minutes: Optional[int] = Field(
        None, description="Estimated reading time"
    )

    # Additional metadata
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional article-specific metadata (e.g., evidence_type, related_question_ids)",
    )

    # Audit timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "art_pol_20240928_001",
                "title": "Pennsylvania Polls Show Tight Race in Key Swing State",
                "content": "Recent polling in Pennsylvania indicates a statistical tie between presidential candidates...",
                "source": "Political Analysis Today",
                "author": "Jane Smith",
                "published_date": "2024-09-28T14:30:00Z",
                "domain": "politics",
                "tags": ["election-2024", "pennsylvania", "polling", "swing-states"],
                "is_synthetic": False,
                "event_ids": ["evt_pol_20240928_001", "evt_pol_20241105_001"],
                "word_count": 1247,
                "reading_time_minutes": 5,
            }
        }
    )

    def compute_reading_time(self) -> int:
        """Calculate estimated reading time in minutes (assuming 200 wpm)."""
        wpm = 200
        if self.word_count:
            return max(1, round(self.word_count / wpm))
        return max(1, round(len(self.content.split()) / wpm))

    def compute_word_count(self) -> int:
        """Calculate word count from content."""
        return len(self.content.split())
