"""
Per-user IndiaMART lead sync service.

Fetches leads from the IndiaMART Pull CRM API, deduplicates by
``unique_query_id`` per tenant, persists new leads, and logs every
sync operation to the ``SyncLog`` table.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from saas.auth import decrypt_api_key
from saas.database import async_session_factory
from saas.models import Lead, SyncLog, User

logger = logging.getLogger(__name__)

# IndiaMART Pull API endpoint
INDIAMART_API_URL = "https://mapi.indiamart.com/wservce/crm/crmListing/v2/"

# Timezone for IndiaMART (IST = UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class SyncResult:
    """Summary returned after a sync operation."""

    user_id: uuid.UUID
    fetched: int = 0
    saved: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    success: bool = True


def _format_indiamart_time(dt: datetime) -> str:
    """Format a datetime as ``DD-MON-YYYY HH:MM:SS`` (uppercase month) for the API.

    Example: ``24-MAR-2026 00:00:00``
    """
    return dt.strftime("%d-%b-%Y %H:%M:%S").upper()


def _parse_query_time(raw: str | None) -> datetime | None:
    """Best-effort parse of IndiaMART's query_time field."""
    if not raw:
        return None
    for fmt in (
        "%d-%b-%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%d-%m-%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(raw.upper() if "%b" in fmt else raw, fmt).replace(
                tzinfo=IST
            )
        except ValueError:
            continue
    return None


async def _fetch_leads_from_api(
    api_key: str,
    start_time: datetime,
    end_time: datetime,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Call the IndiaMART Pull API and return (leads_list, errors).

    Handles HTTP 429 rate-limit responses gracefully by returning an
    empty list and logging the event so the scheduler retries next cycle.
    """
    errors: list[str] = []
    params = {
        "glusr_crm_key": api_key,
        "start_time": _format_indiamart_time(start_time),
        "end_time": _format_indiamart_time(end_time),
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(INDIAMART_API_URL, params=params)

        if resp.status_code == 429:
            logger.warning("IndiaMART rate-limit hit (429) — skipping this cycle")
            errors.append("Rate limited (429) — will retry next cycle")
            return [], errors

        resp.raise_for_status()
        data = resp.json()

        # The API may return an error code inside the JSON body
        if isinstance(data, dict) and data.get("CODE") not in (None, 200, "200"):
            msg = data.get("MESSAGE", "Unknown API error")
            logger.error("IndiaMART API error: %s (code=%s)", msg, data.get("CODE"))
            errors.append(f"API error: {msg}")
            return [], errors

        # Normalise: the API returns a list directly or under a key
        if isinstance(data, list):
            return data, errors
        if isinstance(data, dict):
            # Some responses wrap leads in "JEESSION" or similar
            for key in ("JEESSION", "DATA", "data", "leads"):
                if key in data and isinstance(data[key], list):
                    return data[key], errors
            # Single lead returned as dict — rare but possible
            return [data], errors

        return [], errors

    except httpx.HTTPStatusError as exc:
        msg = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        logger.error("IndiaMART HTTP error: %s", msg)
        errors.append(msg)
        return [], errors
    except httpx.RequestError as exc:
        msg = f"Request error: {exc}"
        logger.error("IndiaMART request failed: %s", msg)
        errors.append(msg)
        return [], errors
    except Exception as exc:  # noqa: BLE001
        msg = f"Unexpected error: {exc}"
        logger.exception("IndiaMART sync unexpected error")
        errors.append(msg)
        return [], errors


async def _save_leads(
    session: AsyncSession,
    user_id: uuid.UUID,
    raw_leads: list[dict[str, Any]],
) -> tuple[int, int]:
    """Persist new leads, skipping duplicates by unique_query_id.

    Returns (saved_count, skipped_count).
    """
    if not raw_leads:
        return 0, 0

    # Collect all unique_query_ids from the batch
    incoming_ids = {
        str(lead.get("UNIQUE_QUERY_ID") or lead.get("unique_query_id", ""))
        for lead in raw_leads
    }
    incoming_ids.discard("")

    # Fetch existing IDs for this user in one query
    existing_result = await session.execute(
        select(Lead.unique_query_id).where(
            Lead.user_id == user_id,
            Lead.unique_query_id.in_(incoming_ids),
        )
    )
    existing_ids: set[str] = {row[0] for row in existing_result.all()}

    saved = 0
    skipped = 0

    for raw in raw_leads:
        # Support both UPPER and lower-case keys from the API
        def _g(key: str) -> Any:
            return raw.get(key.upper()) or raw.get(key.lower()) or raw.get(key)

        uqid = str(_g("UNIQUE_QUERY_ID") or "")
        if not uqid:
            skipped += 1
            continue
        if uqid in existing_ids:
            skipped += 1
            continue

        lead = Lead(
            user_id=user_id,
            unique_query_id=uqid,
            query_type=_g("QUERY_TYPE"),
            query_time=_parse_query_time(_g("QUERY_TIME")),
            sender_name=_g("SENDER_NAME"),
            sender_mobile=_g("SENDER_MOBILE"),
            sender_email=_g("SENDER_EMAIL"),
            subject=_g("SUBJECT"),
            sender_company=_g("SENDER_COMPANY"),
            sender_address=_g("SENDER_ADDRESS"),
            sender_city=_g("SENDER_CITY"),
            sender_state=_g("SENDER_STATE"),
            sender_pincode=_g("SENDER_PINCODE"),
            sender_country=_g("SENDER_COUNTRY_ISO") or _g("SENDER_COUNTRY"),
            query_product_name=_g("QUERY_PRODUCT_NAME"),
            query_message=_g("QUERY_MESSAGE") or _g("QUERY_MCAT_NAME"),
            call_duration=_g("CALL_DURATION"),
            receiver_mobile=_g("RECEIVER_MOBILE"),
        )
        session.add(lead)
        existing_ids.add(uqid)  # prevent intra-batch dupes
        saved += 1

    if saved:
        await session.flush()

    return saved, skipped


async def sync_user_leads(
    user_id: uuid.UUID,
    api_key: str,
    hours: int = 24,
    sync_type: str = "auto",
) -> SyncResult:
    """Fetch and persist IndiaMART leads for a single user.

    Args:
        user_id: The tenant user's UUID.
        api_key: The user's encrypted IndiaMART CRM API key.
        hours: How far back to fetch (default 24 h).
        sync_type: ``"auto"`` or ``"manual"`` — logged in SyncLog.

    Returns:
        A :class:`SyncResult` with counts and any error messages.
    """
    result = SyncResult(user_id=user_id)

    # Decrypt the stored API key
    try:
        plain_key = decrypt_api_key(api_key)
    except ValueError as exc:
        result.errors.append(f"Decryption failed: {exc}")
        result.success = False
        logger.error("API key decryption failed for user %s", user_id)
        # Log the failure
        await _log_sync(user_id, sync_type, result)
        return result

    # Time window
    end_time = datetime.now(IST)
    start_time = end_time - timedelta(hours=hours)

    # Fetch from IndiaMART
    raw_leads, fetch_errors = await _fetch_leads_from_api(plain_key, start_time, end_time)
    result.fetched = len(raw_leads)
    result.errors.extend(fetch_errors)

    if fetch_errors and not raw_leads:
        result.success = False
        await _log_sync(user_id, sync_type, result)
        return result

    # Persist
    async with async_session_factory() as session:
        async with session.begin():
            saved, skipped = await _save_leads(session, user_id, raw_leads)
            result.saved = saved
            result.skipped = skipped

    # Log
    await _log_sync(user_id, sync_type, result)

    logger.info(
        "Sync complete for user %s: fetched=%d saved=%d skipped=%d errors=%d",
        user_id,
        result.fetched,
        result.saved,
        result.skipped,
        len(result.errors),
    )
    return result


async def _log_sync(
    user_id: uuid.UUID,
    sync_type: str,
    result: SyncResult,
) -> None:
    """Write a SyncLog entry."""
    try:
        async with async_session_factory() as session:
            async with session.begin():
                log = SyncLog(
                    user_id=user_id,
                    sync_type=sync_type,
                    leads_fetched=result.fetched,
                    leads_saved=result.saved,
                    status="success" if result.success else "failed",
                    error_message="; ".join(result.errors) if result.errors else None,
                )
                session.add(log)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to write SyncLog for user %s", user_id)
