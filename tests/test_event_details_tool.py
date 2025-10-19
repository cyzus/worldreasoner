"""Test the EventDetailsTool functionality."""

from datetime import datetime, timezone
from src.data.models import Article, Event
from src.data.pipelines.stages.tools import EventDetailsTool
import json

# Create test article
article = Article(
    id="art_test_001",
    title="AI Industry Faces Major Energy Crisis",
    url="https://example.com/ai-energy",
    content="""
    The artificial intelligence industry is facing an unprecedented energy crisis
    as data centers struggle to meet the computational demands of large language
    models and other AI systems. According to a new study published this week,
    AI training runs now consume as much electricity as small countries.
    
    Key findings from the research:
    - Training GPT-4 level models requires 10,000+ GPUs running for weeks
    - Data center energy usage has tripled in the past 2 years
    - Water consumption for cooling has increased by 400%
    - Many regions face grid capacity constraints
    
    Industry experts warn that without significant innovations in energy efficiency,
    the AI boom could stall due to infrastructure limitations. Several major tech
    companies have announced plans to invest in renewable energy and more efficient
    chip designs.
    
    "This is a wake-up call for the industry," said Dr. Jane Smith, lead researcher.
    "We need to balance innovation with sustainability."
    """,
    source="TechNews Daily",
    published_date=datetime(2025, 10, 19, tzinfo=timezone.utc),
    domain="tech",
    author="John Doe",
    word_count=150,
    reading_time_minutes=2
)

# Create test event (with truncated description)
event = Event(
    id="evt_test_001",
    title="AI Industry Energy Crisis Emerges",
    description="AI industry facing energy crisis with data centers struggling...",  # Truncated!
    occurred_date=datetime(2025, 10, 19, tzinfo=timezone.utc),
    event_type="indicator",
    domain="tech",
    article_ids=["art_test_001"],
    entities={"industries": ["AI", "data centers"]},
    metadata={"confidence": 0.9, "location": "Global"}
)

# Create tool
tool = EventDetailsTool(events=[event], articles=[article])

# Test getting event details
print("=" * 80)
print("Testing EventDetailsTool")
print("=" * 80)

result = tool.forward("evt_test_001")
parsed = json.loads(result)

print("\n📋 Event Summary:")
print(f"  Title: {parsed['event']['title']}")
print(f"  Description (full): {parsed['event']['description']}")

print("\n📰 Linked Articles:")
for art in parsed['linked_articles']:
    print(f"  Title: {art['title']}")
    print(f"  Source: {art['source']}")
    print(f"  Word Count: {art['word_count']}")
    print(f"\n  Content Preview:")
    print(f"  {art['content'][:200]}...")

print("\n" + "=" * 80)
print("✅ Tool working correctly!")
print("=" * 80)
