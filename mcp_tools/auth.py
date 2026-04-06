"""
MCP-specific authentication helpers.

For the MCP server (single-user, stdio transport), authentication is handled
via the INDIAMART_API_KEY environment variable. This module provides thin
wrappers for config validation.

For multi-tenant SaaS auth (JWT, OAuth2), see saas/auth.py.
"""

from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

INDIAMART_API_KEY: str = os.getenv("INDIAMART_API_KEY", "")
INDIAMART_GLID: str = os.getenv("INDIAMART_GLID", "")


def is_api_configured() -> bool:
    """Check whether the IndiaMART API credentials are configured."""
    return bool(INDIAMART_API_KEY)


def get_api_key() -> str:
    """Return the configured IndiaMART API key.

    Raises:
        RuntimeError: If the API key is not set.
    """
    if not INDIAMART_API_KEY:
        raise RuntimeError(
            "INDIAMART_API_KEY is not set. "
            "Add it to your .env file or set it as an environment variable. "
            "Get your key from seller.indiamart.com → Lead Manager → Settings → CRM Integration."
        )
    return INDIAMART_API_KEY


def get_glid() -> str | None:
    """Return the configured IndiaMART GLID, or None."""
    return INDIAMART_GLID or None
