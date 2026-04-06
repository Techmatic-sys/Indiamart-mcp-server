"""Resilient HTTP client with retry + backoff for IndiaMART API."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from mcp_tools.auth import INDIAMART_API_KEY

logger = logging.getLogger("indiamart-mcp.http")
INDIAMART_API_URL: str = "https://mapi.indiamart.com/wservce/crm/crmListing/v2/"
API_DATE_FMT: str = "%d-%b-%Y"


async def fetch_with_retry(
    url: str, params: dict, max_retries: int = 3
) -> dict[str, Any]:
    """Call IndiaMART API with exponential backoff on 429/5xx."""
    last_error = None
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params)
                if response.status_code == 429:
                    wait = 2 ** attempt
                    logger.warning("Rate limited, retrying in %ds...", wait)
                    await asyncio.sleep(wait)
                    continue
                response.raise_for_status()
                return response.json()
        except httpx.TimeoutException:
            last_error = f"Request timed out after 30s (attempt {attempt + 1})"
            await asyncio.sleep(2 ** attempt)
        except httpx.HTTPStatusError as e:
            last_error = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            if e.response.status_code < 500:
                break  # 4xx errors won't be fixed by retry
            await asyncio.sleep(2 ** attempt)
        except Exception as e:
            last_error = str(e)
            await asyncio.sleep(2 ** attempt)

    raise RuntimeError(f"API call failed after {max_retries} attempts: {last_error}")


def tool_error(message: str, details: str = "") -> str:
    """Return a consistent error string Claude can understand and act on."""
    out = f"❌ ERROR: {message}"
    if details:
        out += f"\nDetails: {details}"
    return out


def tool_success(message: str, data: str = "") -> str:
    """Return a consistent success string."""
    out = f"✅ {message}"
    if data:
        out += f"\n\n{data}"
    return out


async def fetch_leads_from_api(start_time: str, end_time: str) -> list[dict]:
    """Fetch leads from IndiaMART CRM API with retry logic.

    Args:
        start_time: Start datetime in API format (dd-MMM-yyyy).
        end_time: End datetime in API format.

    Returns:
        List of lead dicts from the API response.

    Raises:
        RuntimeError: On API errors or missing API key.
    """
    if not INDIAMART_API_KEY:
        raise RuntimeError(
            "INDIAMART_API_KEY is not set. "
            "Add it to your .env file or set it as an environment variable. "
            "Get your key from seller.indiamart.com → Lead Manager → Settings → CRM Integration."
        )

    params = {
        "glusr_crm_key": INDIAMART_API_KEY,
        "start_time": start_time.upper(),
        "end_time": end_time.upper(),
    }

    logger.info("Fetching leads from IndiaMART API: %s → %s", start_time, end_time)

    data = await fetch_with_retry(INDIAMART_API_URL, params)

    # The API may return an error dict with CODE/MESSAGE keys
    if isinstance(data, dict) and data.get("CODE") and str(data["CODE"]) != "200":
        msg = data.get("MESSAGE", "Unknown API error")
        raise RuntimeError(f"IndiaMART API error (code {data['CODE']}): {msg}")

    # Successful response — IndiaMART wraps leads in {"CODE": 200, "RESPONSE": [...]}
    if isinstance(data, dict) and "RESPONSE" in data:
        resp = data["RESPONSE"]
        if isinstance(resp, list):
            logger.info(
                "API returned %d leads (TOTAL_RECORDS: %s)",
                len(resp),
                data.get("TOTAL_RECORDS", "?"),
            )
            return resp
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "data" in data:
        return data["data"] if isinstance(data["data"], list) else []
    if isinstance(data, dict) and "UNIQUE_QUERY_ID" in data:
        return [data]

    logger.warning("Unexpected API response format: %s", str(data)[:200])
    return []
