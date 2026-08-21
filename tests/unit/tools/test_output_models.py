"""Tests for unambiguous tool-output model helpers."""

from src.tools.base.output_models import RssFeedItem, RssFetchOutput


def test_rss_items_field_does_not_shadow_mapping_helper() -> None:
    item = RssFeedItem(
        title="Title",
        link="https://example.test/article",
        published="2026-08-21",
        summary="Summary",
    )
    output = RssFetchOutput(
        feed_url="https://example.test/feed",
        total_items=1,
        items=[item],
    )

    assert output.items == [item]
    assert dict(output.model_items())["items"] == [item.model_dump()]
