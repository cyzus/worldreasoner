"""WebSocket endpoints for real-time updates.

Provides WebSocket connections for streaming pipeline progress
and graph updates to the frontend.
"""

from typing import Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.utils.logging import logger


router = APIRouter()


# Active WebSocket connections
active_connections: Set[WebSocket] = set()


@router.websocket("/graph-updates")
async def graph_updates_websocket(websocket: WebSocket):
    """WebSocket endpoint for real-time graph updates.

    Clients connect to receive notifications when:
    - New events are added
    - Causal links are created
    - Pipeline stages complete

    Message format:
    {
        "type": "graph_update",
        "action": "node_added|edge_added|node_updated",
        "data": {...}
    }
    """
    await websocket.accept()
    active_connections.add(websocket)

    logger.info(f"WebSocket connected (total: {len(active_connections)})")

    try:
        # Send initial connection message
        await websocket.send_json(
            {
                "type": "connection",
                "status": "connected",
                "message": "Connected to WorldReasoner graph updates",
            }
        )

        # Keep connection alive
        while True:
            # Wait for messages from client (ping/pong)
            data = await websocket.receive_text()

            # Echo back for heartbeat
            if data == "ping":
                await websocket.send_text("pong")

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        active_connections.discard(websocket)
        logger.info(f"WebSocket closed (remaining: {len(active_connections)})")


async def broadcast_graph_update(update_type: str, data: dict):
    """Broadcast graph update to all connected clients.

    Args:
        update_type: Type of update (node_added, edge_added, etc.)
        data: Update data
    """
    if not active_connections:
        return

    message = {
        "type": "graph_update",
        "action": update_type,
        "data": data,
    }

    # Send to all connected clients
    disconnected = set()
    for websocket in active_connections:
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Failed to send update: {e}")
            disconnected.add(websocket)

    # Clean up disconnected clients
    active_connections.difference_update(disconnected)


@router.websocket("/pipeline-progress")
async def pipeline_progress_websocket(websocket: WebSocket):
    """WebSocket endpoint for pipeline execution progress.

    Clients connect to receive real-time updates about:
    - Pipeline stage progress
    - Articles collected
    - Events identified
    - Questions generated

    Message format:
    {
        "type": "pipeline_progress",
        "pipeline": "question|evidence",
        "stage": "article_collection|event_identification|...",
        "progress": {
            "current": 5,
            "total": 10,
            "percentage": 50.0
        },
        "message": "Collected 5 articles..."
    }
    """
    await websocket.accept()

    logger.info("Pipeline progress WebSocket connected")

    try:
        # Send initial message
        await websocket.send_json(
            {
                "type": "connection",
                "status": "connected",
                "message": "Connected to pipeline progress updates",
            }
        )

        # Keep connection alive
        while True:
            data = await websocket.receive_text()

            if data == "ping":
                await websocket.send_text("pong")

    except WebSocketDisconnect:
        logger.info("Pipeline progress WebSocket disconnected")
    except Exception as e:
        logger.error(f"Pipeline progress WebSocket error: {e}")
