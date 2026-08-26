"""Core utilities for WorldReasoner.

Common functionality shared across the application.
"""

from .database import GenericDatabase, register_model


def __getattr__(name: str):
    """Load optional core services only when callers request them."""
    if name == "ResultCollector":
        from .collectors import ResultCollector

        return ResultCollector
    if name in {"TemporalGateway", "TemporalContext", "ValidationResult"}:
        from .temporal_gateway import (
            TemporalContext,
            TemporalGateway,
            ValidationResult,
        )

        return {
            "TemporalGateway": TemporalGateway,
            "TemporalContext": TemporalContext,
            "ValidationResult": ValidationResult,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "GenericDatabase",
    "register_model",
    "TemporalGateway",
    "TemporalContext",
    "ValidationResult",
    "ResultCollector",
]
