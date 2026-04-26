# WorldReasoner Frontend

Real-time causal graph visualization for WorldReasoner.

## Features

- **Interactive Force-Directed Graph**: Drag, zoom, pan to explore causal relationships
- **Node Filtering**: Filter by domain (politics, economics, technology, etc.)
- **Neighborhood View**: Explore 1-hop or 2-hop neighborhoods around events
- **Event Details**: Click any node to see full event information
- **Real-time Updates**: WebSocket support for live pipeline progress (future)

## Getting Started

### Prerequisites

- Node.js 18+ and npm

### Installation

```bash
cd frontend
npm install
```

### Development

```bash
# Start development server (with hot reload)
npm run dev
```

The frontend will be available at http://localhost:3000

**Note**: Make sure the backend API is running on port 8300:

```bash
# In the project root
uv run worldreasoner --reload
```

### Building for Production

```bash
npm run build
npm run preview
```

## Architecture

### Components

- **App.jsx**: Main application component, manages state and data fetching
- **GraphVisualization**: Force-directed graph using react-force-graph-2d
- **ControlPanel**: Filters and controls for graph queries
- **EventDetails**: Side panel showing detailed event information

### API Client

`src/api/graphApi.js` provides typed API calls to the FastAPI backend:

- `fetchGraph(params)`: Get graph data with filters
- `fetchNode(nodeId)`: Get single node details
- `fetchNeighborhood(nodeId, depth)`: Get node neighborhood
- `fetchPaths(sourceId, targetId)`: Find causal paths
- `fetchStatistics()`: Get graph statistics

### Styling

Dark theme with blue/red accent colors. Uses CSS modules for component isolation.

## Future Enhancements

- WebSocket integration for real-time pipeline updates
- Path highlighting between selected nodes
- 3D graph visualization option
- Timeline view for temporal analysis
- Export graph as image/SVG
