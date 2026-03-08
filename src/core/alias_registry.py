"""In-memory session registry for resolving semantic aliases to event UUIDs."""

from typing import Dict, Optional


class AliasRegistry:
    """A session-local store mapping semantic aliases to event IDs.

    This helps the LLM avoid tracking unwieldy UUIDs across multiple tool calls.
    Aliases look like 'E1:IranStrikes'.
    """

    def __init__(self):
        """Initialize the empty alias registry."""
        self._registry: Dict[str, str] = {}

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

        # CamelCase truncation
        words = [w for w in title.split() if w.isalnum()]
        if not words:
            slug = "Event"
        else:
            slug = "".join(word.capitalize() for word in words[:3])

        alias = f"E{n}:{slug}"
        self.register(alias, event_id)
        return alias
