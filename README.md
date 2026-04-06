# 🇮🇳 IndiaMART MCP Server

<!-- mcp-name: io.github.Techmatic-sys/indiamart-mcp-server -->

![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)
![License MIT](https://img.shields.io/badge/license-MIT-green.svg)
![MCP Compatible](https://img.shields.io/badge/MCP-compatible-purple.svg)
![CI](https://github.com/Techmatic-sys/indiamart-mcp-server/actions/workflows/ci.yml/badge.svg)
![Coverage](https://codecov.io/gh/Techmatic-sys/indiamart-mcp-server/branch/main/graph/badge.svg)

A fully functional **Model Context Protocol (MCP) server** that connects **Claude AI** to **IndiaMART's Lead Management API**. Fetch, search, analyze, and manage your IndiaMART buyer leads using natural language.

## ⚡ Quick Install (60 seconds)

```bash
git clone https://github.com/Techmatic-sys/indiamart-mcp-server.git
cd indiamart-mcp-server
pip install -r requirements.txt
```

Then add to your Claude Desktop config and you're done. Full setup below.

---

## ✨ Features

- **10 MCP Tools** — 8 read tools + 2 write tools for complete CRM
- **Pull Leads** — Fetch leads from IndiaMART for any date range
- **Pipeline Management** — Track leads through sales stages (new → won)
- **Notes** — Attach private notes to leads for context
- **Real-time Webhook** — Receive leads instantly via IndiaMART's Push API
- **Local Database** — All leads stored in SQLite for fast offline access
- **Analytics** — Get stats by city, product, and date
- **Search** — Find leads by keyword in product or message
- **Export CSV** — Export leads for spreadsheets and reporting
- **Draft Replies** — Generate professional buyer replies instantly
- **Input Validation** — Pydantic schemas prevent malformed queries
- **Retry Logic** — Exponential backoff on API failures
- **Claude Desktop Ready** — Plug-and-play config included

---

## 📋 Prerequisites

- **Python 3.10+** ([Download](https://www.python.org/downloads/))
- **IndiaMART Seller Account** with Lead Manager access
- **IndiaMART CRM API Key** (see below)
- **Claude Desktop** (optional, for AI-powered lead management)

---

## 🚀 Installation

### 1. Clone or Download

```bash
git clone https://github.com/Techmatic-sys/indiamart-mcp-server.git
cd indiamart-mcp-server
```

### 2. Create Virtual Environment (recommended)

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

### 3. Install Dependencies

```bash
# MCP server only (lightweight, 4 packages)
pip install -r requirements.txt

# Full SaaS web app (includes FastAPI, uvicorn, etc.)
pip install -r requirements-saas.txt
```

### 4. Configure Environment

```bash
# Copy the example env file
cp .env.example .env    # Linux/macOS
copy .env.example .env  # Windows

# Edit .env with your credentials
```

---

## 🔑 How to Get Your IndiaMART API Key

1. Log in to [IndiaMART Seller Dashboard](https://seller.indiamart.com)
2. Go to **Lead Manager** → **Settings** (⚙️ icon)
3. Navigate to **CRM Integration** or **API Settings**
4. Generate or copy your **CRM API Key** (`glusr_crm_key`)
5. Note your **GLID** (Global Login ID) from your account profile
6. Paste both values into your `.env` file

> **Note:** The API key gives access to your leads. Keep it secret!

---

## ▶️ Running the MCP Server

```bash
# Standard run (Claude Desktop starts this automatically)
python mcp_server.py

# Check version
python mcp_server.py --version

# Health check (verify DB connectivity)
python mcp_server.py --health
```

---

## 🖥️ Connecting to Claude Desktop

### 1. Locate Claude Desktop Config

| OS | Path |
|----|------|
| **Windows** | `%APPDATA%\Claude\claude_desktop_config.json` |
| **macOS** | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| **Linux** | `~/.config/Claude/claude_desktop_config.json` |

### 2. Add the MCP Server

```json
{
  "mcpServers": {
    "indiamart": {
      "command": "python",
      "args": ["mcp_server.py"],
      "cwd": "/ABSOLUTE/PATH/TO/indiamart-mcp-server",
      "env": {
        "INDIAMART_API_KEY": "your_crm_api_key_here",
        "INDIAMART_GLID": "your_glid_here"
      }
    }
  }
}
```

**Replace `cwd` with your actual path:**
- **Windows:** `"C:\\Users\\YourName\\indiamart-mcp-server"`
- **macOS:** `"/Users/yourname/indiamart-mcp-server"`
- **Linux:** `"/home/yourname/indiamart-mcp-server"`

### 3. Restart Claude Desktop

Close and reopen Claude Desktop. You should see the IndiaMART tools available in the tools menu.

---

## 🤖 Connecting to Claude Code

### Option 1: CLI (Recommended)

```bash
claude mcp add indiamart -- python /ABSOLUTE/PATH/TO/indiamart-mcp-server/mcp_server.py
```

Then set your environment variables:

```bash
# In your shell profile or before launching Claude Code
export INDIAMART_API_KEY="your_crm_api_key_here"
export INDIAMART_GLID="your_glid_here"
```

### Option 2: Manual Config

Add to your `.claude/settings.json` (project-level) or `~/.claude/settings.json` (global):

```json
{
  "mcpServers": {
    "indiamart": {
      "command": "python",
      "args": ["/ABSOLUTE/PATH/TO/indiamart-mcp-server/mcp_server.py"],
      "env": {
        "INDIAMART_API_KEY": "your_crm_api_key_here",
        "INDIAMART_GLID": "your_glid_here"
      }
    }
  }
}
```

Replace the path with your actual absolute path to `mcp_server.py`.

### Verify Connection

Once connected, ask Claude Code:
- "Sync my latest IndiaMART leads"
- "Show me leads from the last 24 hours"
- "What are my lead statistics?"

---

## 🦞 Connecting to OpenClaw

[OpenClaw](https://openclaw.ai) is a self-hosted AI agent platform. Your IndiaMART leads
become a native skill in OpenClaw, accessible from any interface OpenClaw supports.

### 1. Find your OpenClaw config file

| OS | Path |
|----|------|
| **Linux/macOS** | `~/.openclaw/openclaw.json` |
| **Windows** | `C:\Users\YourName\.openclaw\openclaw.json` |

### 2. Add the IndiaMART skill

Open the config and add under `skills.mcpServers`:

```json5
{
  skills: {
    mcpServers: {
      indiamart: {
        command: "python",
        args: ["mcp_server.py"],
        cwd: "/absolute/path/to/indiamart-mcp-server",
        env: {
          INDIAMART_API_KEY: "your_crm_api_key_here",
          INDIAMART_GLID: "your_glid_here"
        }
      }
    }
  }
}
```

> See `openclaw-config-example.json5` at the repo root for a ready-to-copy template.

### 3. Restart the OpenClaw gateway

```bash
openclaw gateway restart
```

### 4. Verify it loaded

```bash
openclaw status --all
# You should see "indiamart" listed with 10 tools
```

### Remote OpenClaw (VPS / EC2)

Run the MCP server in SSE mode on your server:

```bash
python mcp_server.py --transport sse --host 0.0.0.0 --port 8000
```

Then point your OpenClaw config to `http://your-server-ip:8000`.

---

## 💬 Example Prompts

| Prompt | What It Does |
|--------|-------------|
| "Show me all leads from the last 24 hours" | Syncs and displays recent leads |
| "How many leads did I get this week and from which cities?" | Shows lead statistics |
| "Search for leads asking about steel pipes" | Keyword search in product/message |
| "Draft a reply for lead ID IML123456789" | Generates professional buyer reply |
| "Move lead IML123 to qualified stage" | Updates pipeline stage |
| "Add a note to lead IML123: Very interested in bulk order" | Attaches a note |
| "Export all leads from January 2026 as CSV" | Exports leads in CSV format |
| "Sync my latest IndiaMART leads" | Pulls latest leads into local DB |

---

## 🛠️ Available MCP Tools (10 Total)

### Read Tools (8)

| Tool | Description |
|------|-------------|
| `tool_get_leads_by_date` | Fetch leads from IndiaMART for a date range |
| `tool_get_recent_leads` | Get leads from the last N hours |
| `tool_get_lead_stats` | Analytics: totals, by city, product, and date |
| `tool_search_leads` | Search leads by keyword |
| `tool_get_lead_by_id` | Full details of a specific lead |
| `tool_draft_reply` | Draft a professional reply for a buyer |
| `tool_export_leads_csv` | Export leads as CSV |
| `tool_sync_latest_leads` | Sync latest from IndiaMART to local DB |

### Write Tools (2 — NEW)

| Tool | Description |
|------|-------------|
| `tool_update_lead_stage` | Move leads through pipeline (new → contacted → qualified → won/lost) |
| `tool_add_note` | Attach private notes to leads for follow-up tracking |

---

## 📁 Project Structure

```
indiamart-mcp-server/
├── 📄 mcp_server.py           ← SINGLE entry point
├── 📄 smithery.yaml            ← Smithery.ai marketplace manifest
├── 📄 pyproject.toml           ← Python package config
├── 📄 requirements.txt         ← MCP only (5 packages)
├── 📄 requirements-saas.txt    ← Web app deps
├── 📄 README.md                ← This file
├── 📄 CHANGELOG.md             ← Version history
├── 📄 LICENSE                  ← MIT License
├── 📄 .env.example             ← Annotated credential guide
├── 📄 .gitignore               ← Git ignore rules
├── 📄 docker-compose.yml       ← Full stack Docker setup
│
├── 📁 mcp_tools/               ← Core MCP Package
│   ├── __init__.py
│   ├── 🔧 tools.py            ← 10 MCP tools with rich docstrings
│   ├── 📋 schemas.py          ← Pydantic validation + response types
│   ├── 🌐 http_client.py      ← Resilient API client with retry
│   ├── 💾 database.py         ← SQLite operations
│   ├── 🔑 auth.py             ← API key helpers
│   └── 🐳 Dockerfile          ← MCP server Docker image
│
├── 📁 saas/                    ← SaaS Web App (FastAPI)
│   └── ...
│
├── 📁 tests/                   ← Test suite
│   ├── conftest.py             ← pytest fixtures
│   └── test_tools.py           ← Validation + integration tests
│
├── 📁 .github/                 ← CI/CD
│   └── workflows/ci.yml
│
└── 📁 docs/                    ← Documentation
    ├── tools.md
    └── examples.md
```

---

## 🔧 Troubleshooting

### "INDIAMART_API_KEY is not set"
- Make sure you've created a `.env` file (not just `.env.example`)
- Check that the key is correct and not expired
- Verify the `.env` file is in the project root directory

### Claude Desktop doesn't show IndiaMART tools
- Restart Claude Desktop completely (quit + reopen)
- Check `claude_desktop_config.json` for syntax errors (valid JSON?)
- Verify the `cwd` path is correct and `mcp_server.py` exists there
- Check Claude Desktop logs for MCP connection errors

### Date format errors
- Supported formats: `YYYY-MM-DD`, `DD-MM-YYYY`, `DD/MM/YYYY`, `DD-Mon-YYYY`
- Example: `2026-01-15`, `15-01-2026`, `15-Jan-2026`

---

## 📄 License

MIT License. Use freely for your business.

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Commit changes: `git commit -m "Add my feature"`
4. Push: `git push origin feature/my-feature`
5. Open a Pull Request

---

**Built with ❤️ for Indian sellers on IndiaMART**
