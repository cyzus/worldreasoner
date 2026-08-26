"""API module for WorldReasoner.

The main application is imported lazily so isolated entry points, including the
hosted annotation service, do not load the full benchmark API and its optional
runtime dependencies.
"""

from typing import Any


def create_app(*args: Any, **kwargs: Any) -> Any:
    """Create the main WorldReasoner API application."""
    from .app import create_app as create_main_app

    return create_main_app(*args, **kwargs)


__all__ = ["create_app"]
