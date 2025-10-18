"""Unit tests for Article model."""

from datetime import datetime

import pytest

from src.data.models import Article


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
    content = "This is a test article with exactly ten words here."
    article = Article(
        id="test_003",
        title="Test Word Count",
        content=content,
        source="Test Source",
        published_date=datetime.now(),
        domain="tech",
    )
    
    word_count = article.compute_word_count()
    assert word_count == 10


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


def test_article_causal_links():
    """Test article with causal links."""
    article = Article(
        id="test_005",
        title="Article with Causal Links",
        content="This article references previous events. " * 20,
        source="Test Source",
        published_date=datetime.now(),
        domain="politics",
        causal_links=["art_pol_001", "art_pol_002"],
    )
    
    assert len(article.causal_links) == 2
    assert "art_pol_001" in article.causal_links


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
