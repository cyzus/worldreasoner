# MCP Forecasting Server

A Model Context Protocol (MCP) server that empowers LLM agents to forecast future events by exploring a simulated past.

## Quick Start

### 1. Installation

```bash
uv sync  # Install dependencies
```

### 2. Configuration

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "worldreasoner": {
      "command": "uv",
      "args": ["run", "worldreasoner-mcp-forecast"],
      "cwd": "/absolute/path/to/worldreasoner"
    }
  }
}
```

### 3. Usage

The server exposes tools that strictly filter information based on a `simulated_date`.
All tools require `X-Simulated-Date` header (handled automatically by the Agent context).

## Available Tools

| Tool Name | Description | Key Inputs |
|-----------|-------------|------------|
| `get_question` | Retrieves the forecasting question without ground truth. | None |
| `temporal_search_articles` | Semantic search for articles published *before* simulated date. | `query`, `limit` |
| `fetch_article` | Gets full content of a specific article. | `article_id` |
| `get_statistics` | Returns server stats (database size, uptime). | None |
| `submit_forecast` | Submit a final prediction. | `prediction`, `confidence`, `reasoning` |

## Resource URIs

-   `forecast://questions/{id}`: Get question details.
-   `forecast://articles/{id}`: Get article content.

## Architecture

The server acts as a **Temporal Gateway**:
1.  Intercepts tool calls.
2.  Checks `X-Simulated-Date` context.
3.  Filters SQL queries to exclude future knowledge.
4.  Returns only "historically accurate" data to the Agent.
