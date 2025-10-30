"""Graph service layer for WorldReasoner.

This module provides an abstraction over graph storage and querying,
allowing easy migration from SQLite to graph databases in the future.
"""

from .interface import GraphService, GraphQuery, GraphNode, GraphEdge, GraphData
from .sqlite_backend import SQLiteGraphService

__all__ = [
    "GraphService",
    "GraphQuery",
    "GraphNode",
    "GraphEdge",
    "GraphData",
    "SQLiteGraphService",
]
