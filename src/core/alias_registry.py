"""In-memory session registry for resolving semantic aliases to UUIDs."""

from typing import Dict, List, Optional


class AliasRegistry:
    """A session-local store mapping semantic aliases to entity IDs.

    This helps the LLM avoid tracking unwieldy UUIDs across multiple tool calls.
    Event aliases look like 'E1:IranStrikes', article aliases like 'A1:BBCSanctions'.
    """

    def __init__(self):
        """Initialize the empty alias registry."""
        self._registry: Dict[str, str] = {}
        self._article_counter: int = 0

    def register(self, alias: str, event_id: str) -> None:
        """Register an alias pointing to a specific event ID.

        Args:
            alias: The short semantic label (e.g. E1:IranStrikes)
            event_id: The actual UUID in the database
        """
        self._registry[alias] = event_id

    def resolve(self, alias_or_id: str) -> Optional[str]:
        """Resolve an alias to an event ID.

        If the input is already an ID (not in registry), returns the input.

        Args:
            alias_or_id: The alias string or a raw UUID

        Returns:
            The resolved UUID, or the input if it's not a known alias
        """
        if not alias_or_id:
            return None
        return self._registry.get(alias_or_id, alias_or_id)

    def list_aliases(self) -> Dict[str, str]:
        """Get the full mapping of all known aliases.

        Returns:
            Dict mapping aliases to event IDs
        """
        return self._registry.copy()

    def clear(self) -> None:
        """Clear the registry (useful for testing or resetting session)."""
        self._registry.clear()

    def generate_alias(self, title: str, event_id: str) -> str:
        """Generate a new alias for a title, register it, and return it.

        Format: E{n}:{camelCaseTruncatedTitle}

        Args:
            title: Title of the event
            event_id: Event ID to map to

        Returns:
            The newly generated alias string
        """
        n = len(self._registry) + 1

        slug = self._make_slug(title, fallback="Event")

        alias = f"E{n}:{slug}"
        self.register(alias, event_id)
        return alias

    def generate_article_alias(self, title: str, article_id: str) -> str:
        """Generate a new alias for an article, register it, and return it.

        Format: A{n}:{camelCaseTruncatedTitle}

        Args:
            title: Title of the article
            article_id: Article ID to map to

        Returns:
            The newly generated alias string
        """
        self._article_counter += 1

        slug = self._make_slug(title, fallback="Article")

        alias = f"A{self._article_counter}:{slug}"
        self.register(alias, article_id)
        return alias

    def resolve_article_ids(self, comma_separated: str) -> str:
        """Resolve a comma-separated string of article aliases/IDs.

        Each token is resolved through the registry. Raw IDs pass through unchanged.

        Args:
            comma_separated: e.g. "A1:BBCSanctions,art_tech_20240101_001_abc"

        Returns:
            Comma-separated resolved IDs
        """
        if not comma_separated:
            return ""
        resolved = [
            self.resolve(token.strip()) or token.strip()
            for token in comma_separated.split(",")
            if token.strip()
        ]
        return ",".join(resolved)

    @staticmethod
    def _make_slug(title: str, fallback: str = "Item") -> str:
        """Create a CamelCase slug from a title.

        Args:
            title: Source title string
            fallback: Default slug if title has no usable words

        Returns:
            CamelCase slug from first 3 words
        """
        words = [w for w in title.split() if w.isalnum()]
        if not words:
            return fallback
        return "".join(word.capitalize() for word in words[:3])
