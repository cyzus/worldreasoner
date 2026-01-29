"""Unit tests for Article model."""

from datetime import datetime

import pytest

from src.domain.models import Article


def test_article_creation():
    """Test basic article creation."""
    article = Article(
        id="test_001",
        title="Test Article Title",
        content="This is the content of the test article. " * 20,  # Make it long enough
        source="Test Source",
        published_date=datetime(2024, 9, 28, 14, 30, 0),
        domain="politics",
    )

    assert article.id == "test_001"
    assert article.title == "Test Article Title"
    assert article.domain == "politics"
    assert article.is_synthetic is False
    assert article.language == "en"


def test_article_with_tags():
    """Test article with tags."""
    article = Article(
        id="test_002",
        title="Test Article with Tags",
        content="Content goes here. " * 20,
        source="Test Source",
        published_date=datetime.now(),
        domain="finance",
        tags=["stocks", "trading", "market"],
    )

    assert len(article.tags) == 3
    assert "stocks" in article.tags


def test_article_compute_word_count():
    """Test word count computation."""
    content = (
        "This is a test article with enough content to pass the minimum length requirement. "
        * 2
    )
    article = Article(
        id="test_003",
        title="Test Word Count",
        content=content,
        source="Test Source",
        published_date=datetime.now(),
        domain="tech",
    )

    word_count = article.compute_word_count()
    assert word_count > 0


def test_article_compute_reading_time():
    """Test reading time computation."""
    # 200 words should be 1 minute at 200 wpm
    content = " ".join(["word"] * 200)
    article = Article(
        id="test_004",
        title="Test Reading Time",
        content=content,
        source="Test Source",
        published_date=datetime.now(),
        domain="health",
        word_count=200,
    )

    reading_time = article.compute_reading_time()
    assert reading_time == 1


def test_article_event_ids():
    """Test article with event references."""
    article = Article(
        id="test_005",
        title="Article with Event References",
        content="This article references previous events and discusses their outcomes. "
        * 10,
        source="Test Source",
        published_date=datetime.now(),
        domain="politics",
        event_ids=["evt_pol_001", "evt_pol_002"],
    )

    assert len(article.event_ids) == 2
    assert "evt_pol_001" in article.event_ids


def test_article_validation_short_title():
    """Test that short titles fail validation."""
    with pytest.raises(ValueError):
        Article(
            id="test_006",
            title="Short",  # Too short
            content="Content goes here. " * 20,
            source="Test Source",
            published_date=datetime.now(),
            domain="tech",
        )


def test_article_validation_short_content():
    """Test that short content fails validation."""
    with pytest.raises(ValueError):
        Article(
            id="test_007",
            title="Valid Title Here",
            content="Too short",  # Too short
            source="Test Source",
            published_date=datetime.now(),
            domain="tech",
        )


def test_article_json_serialization():
    """Test article can be serialized to JSON."""
    article = Article(
        id="test_010",
        title="Test JSON Serialization",
        content="This tests JSON serialization. " * 20,
        source="Test Source",
        published_date=datetime(2024, 9, 28, 14, 30, 0),
        domain="climate",
        tags=["environment", "policy"],
    )

    json_str = article.model_dump_json()
    assert "test_010" in json_str
    assert "climate" in json_str
    assert "environment" in json_str


def test_article_metadata():
    """Test article metadata field."""
    article = Article(
        id="test_011",
        title="Test Article Metadata",
        content="This tests the metadata field functionality. " * 20,
        source="Test Source",
        published_date=datetime.now(),
        domain="tech",
    )

    # Metadata should be empty dict by default
    assert article.metadata == {}

    # Can add metadata
    article.metadata["evidence_type"] = "hindsight"
    article.metadata["related_question_ids"] = ["q_001", "q_002"]
    article.metadata["custom_field"] = "custom_value"

    assert article.metadata["evidence_type"] == "hindsight"
    assert len(article.metadata["related_question_ids"]) == 2
    assert article.metadata["custom_field"] == "custom_value"


def test_article_metadata_at_creation():
    """Test creating article with metadata."""
    article = Article(
        id="test_012",
        title="Test Article with Initial Metadata",
        content="This tests creating article with metadata at instantiation. " * 20,
        source="Test Source",
        published_date=datetime.now(),
        domain="finance",
        metadata={
            "evidence_type": "hindsight",
            "confidence": 0.8,
            "source_pipeline": "evidence",
        },
    )

    assert article.metadata["evidence_type"] == "hindsight"
    assert article.metadata["confidence"] == 0.8
    assert article.metadata["source_pipeline"] == "evidence"
