"""Graph API endpoints.

Provides REST API for querying and visualizing the causal graph.
"""

from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Query, HTTPException, Depends

from src.services.graph import GraphQuery, GraphData, SQLiteGraphService
from src.api.routes.database import get_current_db_path
from src.utils.logging import logger


router = APIRouter()


# Dependency for getting graph service
def get_graph_service() -> SQLiteGraphService:
    """Dependency to get graph service instance."""
    return SQLiteGraphService(get_current_db_path())


@router.get("/", response_model=GraphData)
async def get_graph(
    # Node filtering
    node_ids: Optional[str] = Query(None, description="Comma-separated node IDs"),
    node_types: Optional[str] = Query(None, description="Comma-separated node types"),
    exclude_node_types: Optional[str] = Query(
        None, description="Node types to exclude"
    ),
    # Edge filtering
    edge_types: Optional[str] = Query(None, description="Comma-separated edge types"),
    min_edge_weight: Optional[float] = Query(None, ge=0.0, le=1.0),
    # Temporal filtering
    start_date: Optional[datetime] = Query(None, description="Start date (ISO format)"),
    end_date: Optional[datetime] = Query(None, description="End date (ISO format)"),
    # Neighborhood query
    center_node_id: Optional[str] = Query(
        None, description="Center node for neighborhood query"
    ),
    max_depth: Optional[int] = Query(
        None, ge=1, le=5, description="Max depth for neighborhood"
    ),
    # Outcome impact filtering
    include_outcomes: bool = Query(False, description="Include outcome impact edges"),
    outcome_question_id: Optional[str] = Query(
        None, description="Filter outcomes to specific question"
    ),
    # Limits
    max_nodes: Optional[int] = Query(
        100, ge=1, le=10000
    ),  # Increased to support larger graphs
    max_edges: Optional[int] = Query(500, ge=1, le=20000),  # Increased proportionally
    # Dependency injection
    graph_service: SQLiteGraphService = Depends(get_graph_service),
):
    """Get graph data with optional filtering.

    This endpoint supports multiple query modes:
    1. Full graph: No parameters (limited by max_nodes/max_edges)
    2. Filtered graph: Use node_types, edge_types, date ranges
    3. Neighborhood: Specify center_node_id and max_depth
    4. Specific nodes: Provide comma-separated node_ids

    Examples:
        - Get full graph: GET /api/graph/
        - Get politics nodes: GET /api/graph/?node_types=politics
        - Get neighborhood: GET /api/graph/?center_node_id=evt_123&max_depth=2
        - Get by date: GET /api/graph/?start_date=2024-01-01T00:00:00Z
    """
    try:
        # Parse comma-separated lists
        node_ids_list = (
            [n.strip() for n in node_ids.split(",") if n.strip()] if node_ids is not None else None
        )
        node_types_list = (
            [t.strip() for t in node_types.split(",") if t.strip()] if node_types is not None else None
        )
        exclude_types_list = (
            [t.strip() for t in exclude_node_types.split(",") if t.strip()]
            if exclude_node_types is not None
            else None
        )
        edge_types_list = (
            [t.strip() for t in edge_types.split(",") if t.strip()] if edge_types is not None else None
        )
        # Build query
        query = GraphQuery(
            node_ids=node_ids_list,
            node_types=node_types_list,
            exclude_node_types=exclude_types_list,
            edge_types=edge_types_list,
            min_edge_weight=min_edge_weight,
            start_date=start_date,
            end_date=end_date,
            center_node_id=center_node_id,
            max_depth=max_depth,
            include_outcomes=include_outcomes,
            outcome_question_id=outcome_question_id,
            max_nodes=max_nodes,
            max_edges=max_edges,
        )

        # Get graph data
        graph_data = await graph_service.get_graph(query)

        logger.info(
            f"Graph query returned {len(graph_data.nodes)} nodes, "
            f"{len(graph_data.edges)} edges"
        )

        return graph_data

    except Exception as e:
        logger.error(f"Graph query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/node/{node_id}")
async def get_node(
    node_id: str,
    graph_service: SQLiteGraphService = Depends(get_graph_service),
):
    """Get a single node by ID.

    Args:
        node_id: Node identifier

    Returns:
        Node data
    """
    try:
        node = await graph_service.get_node(node_id)

        if not node:
            raise HTTPException(status_code=404, detail=f"Node {node_id} not found")

        return node

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get node failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/neighborhood/{node_id}", response_model=GraphData)
async def get_neighborhood(
    node_id: str,
    max_depth: int = Query(1, ge=1, le=5),
    direction: str = Query("both", regex="^(incoming|outgoing|both)$"),
    graph_service: SQLiteGraphService = Depends(get_graph_service),
):
    """Get the neighborhood around a node.

    Args:
        node_id: Center node ID
        max_depth: Maximum traversal depth (1-5)
        direction: "incoming", "outgoing", or "both"

    Returns:
        Graph data containing neighborhood
    """
    try:
        graph_data = await graph_service.get_neighborhood(
            node_id, max_depth=max_depth, direction=direction
        )

        logger.info(
            f"Neighborhood query for {node_id} returned "
            f"{len(graph_data.nodes)} nodes, {len(graph_data.edges)} edges"
        )

        return graph_data

    except Exception as e:
        logger.error(f"Neighborhood query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/paths/{source_id}/{target_id}")
async def find_paths(
    source_id: str,
    target_id: str,
    max_depth: int = Query(5, ge=1, le=10),
    graph_service: SQLiteGraphService = Depends(get_graph_service),
):
    """Find causal paths between two nodes.

    Args:
        source_id: Starting node ID
        target_id: Ending node ID
        max_depth: Maximum path length (1-10)

    Returns:
        List of paths (each path is a list of node IDs)
    """
    try:
        paths = await graph_service.find_paths(
            source_id, target_id, max_depth=max_depth
        )

        logger.info(f"Found {len(paths)} paths from {source_id} to {target_id}")

        return {"paths": paths, "count": len(paths)}

    except Exception as e:
        logger.error(f"Path finding failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/statistics")
async def get_statistics(
    graph_service: SQLiteGraphService = Depends(get_graph_service),
):
    """Get graph statistics.

    Returns:
        Dictionary with statistics like total_nodes, total_edges, etc.
    """
    try:
        stats = await graph_service.get_statistics()

        return stats

    except Exception as e:
        logger.error(f"Get statistics failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
