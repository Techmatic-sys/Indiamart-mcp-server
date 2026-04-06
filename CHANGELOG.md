# Changelog

All notable changes to IndiaMART MCP Server.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

## [1.1.0] — 2026-04-06

### Changed
- Expanded FastMCP instructions for better Claude integration
- Improved error messages with actionable guidance (links to IndiaMART settings)
- Removed generic error suffix from `tool_error()` — each tool now provides specific guidance
- Consolidated API key loading through `auth.py` (single source of truth)
- Replaced internal function name references in user-facing messages with natural language
- Fixed Dockerfile: corrected requirements filename, removed non-existent COPY targets
- Fixed pyproject.toml classifier (was Point-Of-Sale, now Office/Business)
- Removed `saas*` from package include — SaaS app is separate from MCP server
- Removed deprecated `version` key from docker-compose.yml

### Added
- `CLAUDE.md` for Claude Code project integration
- "Connecting to Claude Code" section in README with CLI and manual config options
- `.claude/settings.local.json` added to `.gitignore`

### Fixed
- Version consistency: all files now report 1.1.0

## [1.0.1] — 2026-03-26

### Changed
- README install method changed from pip to git clone (PyPI publish pending)
- Removed pitch deck files from repo root (not part of MCP server)
- Added OpenClaw skill configuration guide and example config file
- Added pytest-cov coverage reporting to CI pipeline

## [1.0.0] — 2026-03-25

### Added
- Initial release of IndiaMART MCP Server
- 10 MCP tools for lead management (8 read + 2 write)
- `tool_get_leads_by_date` — Fetch leads for a date range
- `tool_get_recent_leads` — Get leads from the last N hours
- `tool_search_leads` — Search leads by keyword
- `tool_get_lead_by_id` — Full details of a specific lead
- `tool_export_leads_csv` — Export leads as CSV
- `tool_sync_latest_leads` — Sync from IndiaMART API
- `tool_get_lead_stats` — Analytics and statistics
- `tool_draft_reply` — Draft professional buyer replies
- `tool_update_lead_stage` — Pipeline stage management (NEW)
- `tool_add_note` — Attach notes to leads (NEW)
- SQLite local database for offline access
- Pydantic input validation for all tools
- Resilient HTTP client with retry logic and exponential backoff
- Webhook receiver for real-time lead pushes
- Claude Desktop integration config
- Smithery.ai marketplace manifest
- Docker Compose for full-stack deployment
- GitHub Actions CI/CD pipeline
- Comprehensive test suite

## [Unreleased]

### Planned
- PyPI publication for `pip install indiamart-mcp-server`
- Lead scoring with AI-powered qualification
- WhatsApp integration for direct buyer messaging
