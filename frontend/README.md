# WorldReasoner Frontend

Interactive causal graph visualization and research dashboard for WorldReasoner.

## Features

- **Event Graph Visualization** — Force-directed graph for exploring causal relationships between events
- **Question & Forecast Management** — Create, track, and compare forecasting questions
- **Evidence Collection Pipeline** — Run and monitor evidence collection jobs with real-time WebSocket progress
- **Benchmark Dashboard** — Compare model performance across conditions with evaluation metrics
- **Case Study View** — Deep analysis of outcomes: causal trajectories, market price movements, impact assessment
- **Database Switcher** — Switch between, or create new, SQLite databases for different datasets
- **Search Index Management** — Build and rebuild FTS5 + semantic embedding indexes

## Getting Started

### Prerequisites

- Node.js 18+
- WorldReasoner backend running (see root README)

### Installation

```bash
cd frontend
npm install
```

### Development

```bash
npm run dev
```

The frontend will be available at **http://localhost:5173** by default (or `FRONTEND_PORT` if set).

The Vite dev server proxies `/api` and `/ws` requests to the backend. Backend port
is resolved in this order:

1. `BACKEND_PORT` env var (frontend-specific override)
2. `WORLDREASONER__SERVER__PORT` env var (shared with backend)
3. `config/config.yaml` → `server.port`
4. `config/config.example.yaml` → `server.port`
5. Fallback: `8300`

Make sure the backend is running on the same resolved port:

```bash
# From the project root
uv run worldreasoner --reload
```

### Environment configuration

Copy `.env.example` to `.env` in the **project root** (not `frontend/`) and adjust
as needed:

```bash
cp .env.example .env
```

Frontend-only overrides (optional) can be set in `frontend/.env`:

```
FRONTEND_PORT=5173
FRONTEND_HOST=localhost
BACKEND_PORT=8300
```

### Building for production

```bash
npm run build   # outputs to frontend/dist/
npm run preview # preview the production build locally
```

## Architecture

### Component structure

```
src/
├── api/          # HTTP and WebSocket API layer
│   ├── graphApi.js        # All REST endpoints (via axios)
│   └── polymarketApi.js   # Polymarket search wrapper
├── components/   # React UI components (60+ files)
│   ├── EventGraphsPage    # Main graph view
│   ├── BenchmarkPage      # Benchmark results
│   ├── ForecastPage       # Forecast management
│   ├── PipelinePage       # Evidence collection pipeline
│   └── ...
├── hooks/        # Custom React hooks
│   ├── queries/           # React Query hooks
│   ├── useAppData.js      # Global data loading
│   ├── useGraphTraversal.js # Graph navigation
│   └── ...
├── stores/       # Zustand global state
│   ├── graphStore.js
│   ├── questionStore.js
│   └── uiStore.js
└── lib/
    └── queryClient.js     # React Query client config
```

### Tech stack

| Layer | Library |
|---|---|
| UI framework | React 18 |
| Build tool | Vite 6 |
| Server state | TanStack React Query |
| Client state | Zustand |
| HTTP | Axios |
| Graph rendering | react-force-graph-2d + D3 |
| Markdown | react-markdown + remark-gfm |

### API proxy

All `/api/*` calls are proxied to the backend in development. In production, serve
the built `dist/` from a web server that also reverse-proxies `/api` to the
FastAPI backend (e.g. nginx, caddy, or the built-in `worldreasoner` server which
serves `dist/` directly on the same port).
