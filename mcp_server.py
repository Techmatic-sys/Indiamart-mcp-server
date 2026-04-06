# mcp_server.py ← THE ONLY entry point
"""IndiaMART MCP Server — Entry Point."""

import asyncio
import argparse
import sys

from mcp.server.fastmcp import FastMCP
from mcp_tools.tools import register_all_tools
from mcp_tools.database import init_db

__version__ = "1.1.0"

mcp = FastMCP(
    "IndiaMART Lead Manager",
    instructions=(
        "You are connected to the IndiaMART Lead Manager MCP server. "
        "This gives you access to a seller's IndiaMART buyer enquiries (leads). "
        "You can: fetch leads by date range or recency, search by keyword, "
        "view full lead details, export to CSV, track leads through a sales "
        "pipeline (new/contacted/qualified/proposal/negotiation/won/lost), "
        "attach private notes, generate analytics (by city, product, date), "
        "and draft professional buyer replies. "
        "Always sync leads first if the database appears empty. "
        "Date inputs accept YYYY-MM-DD, DD-MM-YYYY, or DD/MM/YYYY formats."
    ),
)
register_all_tools(mcp)


def main() -> None:
    """CLI entry point for the IndiaMART MCP Server."""
    parser = argparse.ArgumentParser(description="IndiaMART MCP Server")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--health", action="store_true", help="Run health check and exit"
    )
    parser.add_argument(
        "--transport", choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transport mode: stdio (Claude Desktop), sse or streamable-http (local server)"
    )
    parser.add_argument(
        "--port", type=int, default=8000,
        help="Port for HTTP transports (default: 8000)"
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Host for HTTP transports (default: 127.0.0.1)"
    )
    args = parser.parse_args()

    if args.health:
        asyncio.run(_health_check())
        sys.exit(0)

    asyncio.run(init_db())

    # Configure host/port for HTTP modes
    if args.transport in ("sse", "streamable-http"):
        mcp.settings.host = args.host
        mcp.settings.port = args.port

    mcp.run(transport=args.transport)


async def _health_check():
    """Check database connectivity and report lead count."""
    from mcp_tools.database import get_leads_count

    await init_db()
    count = await get_leads_count()
    print(f"OK - DB reachable | Leads in DB: {count}")


if __name__ == "__main__":
    main()
