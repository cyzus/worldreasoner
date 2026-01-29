"""Graph service interface and data models.

This module defines the abstract interface for graph operations,
enabling future backend implementations (Neo4j, ArangoDB, etc.)
without changing application code.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class GraphNode(BaseModel):
    """A node in the causal graph."""

    id: str = Field(..., description="Unique node identifier")
    label: str = Field(..., description="Human-readable label")
    node_type: str = Field(..., description="Type of node (event, article, etc.)")
    properties: Dict[str, Any] = Field(
        default_factory=dict, description="Additional node properties"
    )

    # Visual properties
    size: float = Field(default=1.0, description="Visual size (importance)")
    color: Optional[str] = Field(None, description="Visual color category")


class GraphEdge(BaseModel):
    """An edge in the causal graph."""

    source_id: str = Field(..., description="Source node ID")
    target_id: str = Field(..., description="Target node ID")
    edge_type: str = Field(..., description="Type of edge (causes, mentions, etc.)")
    properties: Dict[str, Any] = Field(
        default_factory=dict, description="Additional edge properties"
    )

    # Visual properties
    weight: float = Field(default=1.0, description="Edge weight/strength")
    label: Optional[str] = Field(None, description="Edge label")


class GraphQuery(BaseModel):
    """Query parameters for graph retrieval."""

    # Node filtering
    node_ids: Optional[List[str]] = Field(
        None, description="Specific node IDs to include"
    )
    node_types: Optional[List[str]] = Field(None, description="Filter by node types")
    exclude_node_types: Optional[List[str]] = Field(
        None, description="Exclude specific node types"
    )

    # Edge filtering
    edge_types: Optional[List[str]] = Field(None, description="Filter by edge types")
    min_edge_weight: Optional[float] = Field(
        None, description="Minimum edge weight threshold"
    )

    # Temporal filtering
    start_date: Optional[datetime] = Field(None, description="Start of time window")
    end_date: Optional[datetime] = Field(None, description="End of time window")

    # Graph traversal
    center_node_id: Optional[str] = Field(
        None, description="Center node for neighborhood queries"
    )
    max_depth: Optional[int] = Field(
        None, description="Maximum traversal depth from center node"
    )

    # Outcome impact filtering
    include_outcomes: bool = Field(
        False, description="Include outcome impact edges in graph"
    )
    outcome_question_id: Optional[str] = Field(
        None, description="Filter outcome impacts to specific question"
    )

    # Limits
    max_nodes: Optional[int] = Field(
        None, description="Maximum number of nodes to return"
    )
    max_edges: Optional[int] = Field(
        None, description="Maximum number of edges to return"
    )


class GraphData(BaseModel):
    """Complete graph data structure."""

    nodes: List[GraphNode] = Field(default_factory=list)
    edges: List[GraphEdge] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Graph-level metadata"
    )


class GraphService(ABC):
    """Abstract interface for graph operations.

    This interface allows swapping between different graph backends
    (SQLite, Neo4j, ArangoDB) without changing application code.

    Implementations must handle:
    1. Graph data retrieval and filtering
    2. Graph traversal and pathfinding
    3. Graph statistics and analytics
    4. Real-time updates (for WebSocket support)
    """

    @abstractmethod
    async def get_graph(self, query: Optional[GraphQuery] = None) -> GraphData:
        """Retrieve graph data based on query parameters.

        Args:
            query: Optional query to filter/constrain the graph

        Returns:
            GraphData with nodes and edges
        """
        pass

    @abstractmethod
    async def get_node(self, node_id: str) -> Optional[GraphNode]:
        """Get a single node by ID.

        Args:
            node_id: Node identifier

        Returns:
            GraphNode if found, None otherwise
        """
        pass

    @abstractmethod
    async def get_neighborhood(
        self, node_id: str, max_depth: int = 1, direction: str = "both"
    ) -> GraphData:
        """Get the neighborhood around a node.

        Args:
            node_id: Center node ID
            max_depth: Maximum traversal depth (1 = immediate neighbors)
            direction: "incoming", "outgoing", or "both"

        Returns:
            GraphData containing neighborhood
        """
        pass

    @abstractmethod
    async def find_paths(
        self, source_id: str, target_id: str, max_depth: int = 5
    ) -> List[List[str]]:
        """Find causal paths between two nodes.

        Args:
            source_id: Starting node ID
            target_id: Ending node ID
            max_depth: Maximum path length

        Returns:
            List of paths (each path is a list of node IDs)
        """
        pass

    @abstractmethod
    async def get_statistics(self) -> Dict[str, Any]:
        """Get graph statistics.

        Returns:
            Dictionary with statistics like:
            - total_nodes
            - total_edges
            - node_type_counts
            - edge_type_counts
            - average_degree
            - etc.
        """
        pass

    @abstractmethod
    async def get_outcome_events(self, question_id: str) -> List[GraphNode]:
        """Get outcome events for a specific question.

        Args:
            question_id: Question ID to get outcomes for

        Returns:
            List of GraphNodes representing outcome events
        """
        pass

    @abstractmethod
    async def get_impact_edges(
        self,
        outcome_event_id: Optional[str] = None,
        event_id: Optional[str] = None,
        min_confidence: Optional[float] = None,
        impact_direction: Optional[str] = None,
    ) -> List[GraphEdge]:
        """Get impact edges with optional filtering.

        Args:
            outcome_event_id: Filter impacts to this outcome event
            event_id: Filter impacts from this event
            min_confidence: Minimum confidence threshold
            impact_direction: Filter by impact direction (positive, negative, etc.)

        Returns:
            List of GraphEdges representing impact relationships
        """
        pass

    @abstractmethod
    async def subscribe_to_updates(self, callback) -> None:
        """Subscribe to real-time graph updates.

        Args:
            callback: Async function called when graph changes
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources."""
        pass
