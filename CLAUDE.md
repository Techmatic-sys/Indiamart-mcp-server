# IndiaMART MCP Server

MCP server that connects Claude to IndiaMART's Lead Management API, enabling sellers to manage buyer leads via natural language.

## Architecture

```
mcp_server.py          <- Single entry point (FastMCP, CLI args)
  └── mcp_tools/
      ├── tools.py     <- 10 MCP tool implementations (register_all_tools)
      ├── schemas.py   <- Pydantic input validation
      ├── http_client.py <- IndiaMART API client with retry/backoff
      ├── database.py  <- SQLite async operations (aiosqlite)
      └── auth.py      <- API key helpers (single source of truth)
```

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your INDIAMART_API_KEY and INDIAMART_GLID
```

## Running

```bash
python mcp_server.py                    # stdio (default, for Claude Desktop/Code)
python mcp_server.py --transport sse    # HTTP SSE mode
python mcp_server.py --health           # Check DB connectivity
python mcp_server.py --version          # Show version
```

## Testing

```bash
pytest tests/ -v
ruff check .
```

## Key Conventions

- All tools registered via `register_all_tools(mcp)` in `tools.py`
- Input validation: Pydantic models in `schemas.py`
- Response formatting: `tool_error()` and `tool_success()` helpers in `http_client.py`
- Date formats accepted: YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY, DD-Mon-YYYY
- Pipeline stages: new, contacted, qualified, proposal, negotiation, won, lost
- Database: SQLite via aiosqlite, lazy-initialized on first tool call
- API key: loaded from env via `auth.py`, used by `http_client.py`

## Out of Scope

- `saas/` — Separate FastAPI SaaS web platform (multi-tenant, PostgreSQL, Redis). Not part of the MCP server.
- `webhook.py` — Standalone FastAPI webhook receiver. Not part of the MCP server.
