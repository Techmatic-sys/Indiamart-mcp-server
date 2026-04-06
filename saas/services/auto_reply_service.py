"""
Auto Reply Orchestrator — processes new leads through the AI pipeline.

Coordinates lead scoring, AI reply generation, delivery, notifications,
and user settings management.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from saas.config import PLAN_LIMITS
from saas.models import AutoReply, Lead, User
from saas.services.ai_service import (
    categorize_lead,
    generate_reply,
    score_lead,
)
from saas.services.notification_service import (
    notify_new_lead,
    send_email_notification,
    send_whatsapp_notification,
)

logger = logging.getLogger(__name__)


# ─── Auto-reply settings (stored as JSON in a future UserSettings table) ─────
# For now we use sensible defaults and allow per-request overrides.

_DEFAULT_SETTINGS: dict[str, Any] = {
    "auto_reply_enabled": False,
    "auto_send_enabled": False,
    "preferred_channel": "email",        # "email" | "whatsapp"
    "product_info": "",                   # seller's product blurb
    "seller_name": "",                    # overrides user.name if set
    "notification_preferences": {
        "email_enabled": True,
        "whatsapp_enabled": False,
    },
}

# In-memory store keyed by str(user_id).  Replace with a DB-backed
# ``UserSettings`` model when ready.
_user_settings_cache: dict[str, dict[str, Any]] = {}


# ─── Settings helpers ────────────────────────────────────────────────────────


async def get_user_auto_reply_settings(
    user_id: str | uuid.UUID,
    db: AsyncSession | None = None,
) -> dict[str, Any]:
    """Return the auto-reply settings for a user.

    Falls back to ``_DEFAULT_SETTINGS`` if nothing has been saved yet.

    Args:
        user_id: UUID of the user.
        db: Optional async session (reserved for future DB-backed storage).

    Returns:
        Dict of settings.
    """
    key = str(user_id)
    return {**_DEFAULT_SETTINGS, **_user_settings_cache.get(key, {})}


async def update_auto_reply_settings(
    user_id: str | uuid.UUID,
    settings: dict[str, Any],
    db: AsyncSession | None = None,
) -> None:
    """Persist auto-reply settings for a user.

    Args:
        user_id: UUID of the user.
        settings: Partial dict of settings to merge/update.
        db: Optional async session (reserved for future DB-backed storage).
    """
    key = str(user_id)
    existing = _user_settings_cache.get(key, {})
    existing.update(settings)
    _user_settings_cache[key] = existing
    logger.info("Updated auto-reply settings for user %s", key)


# ─── Core pipeline ───────────────────────────────────────────────────────────


async def process_new_lead(
    user_id: str | uuid.UUID,
    lead: dict[str, Any],
    db: AsyncSession | None = None,
) -> dict[str, Any]:
    """Run the full AI pipeline on a newly received lead.

    Steps:
        1. Score the lead.
        2. If the user has auto-reply enabled **and** their plan allows it:
           a. Generate an AI reply.
           b. Save to the ``auto_replies`` table with status ``"pending"``.
           c. If auto-send is enabled, deliver via the preferred channel.
           d. Update the lead row with ``ai_reply_text`` / ``ai_reply_sent``.
        3. Send a new-lead notification to the user.
        4. Return a summary dict.

    Args:
        user_id: UUID of the tenant user.
        lead: Dict with standard IndiaMART lead fields **plus** ``id`` (the
            Lead row UUID) if already persisted.
        db: Async DB session for persistence.  When ``None`` the function
            still scores/generates but skips DB writes.

    Returns:
        Dict with keys ``score``, ``category``, ``auto_reply_generated``,
        ``auto_reply_sent``, ``notification_results``.
    """
    uid = str(user_id)

    # 1. Score & categorize
    lead_score = score_lead(lead)
    category = categorize_lead(lead)

    result: dict[str, Any] = {
        "score": lead_score,
        "category": category,
        "auto_reply_generated": False,
        "auto_reply_sent": False,
        "auto_reply_text": None,
        "notification_results": [],
    }

    # Fetch settings & plan limits
    user_settings = await get_user_auto_reply_settings(user_id)
    user_obj: User | None = None
    plan = "free"

    if db is not None:
        stmt = select(User).where(User.id == uuid.UUID(uid) if isinstance(user_id, str) else user_id)
        row = await db.execute(stmt)
        user_obj = row.scalar_one_or_none()
        if user_obj:
            plan = user_obj.plan or "free"

    plan_limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])

    auto_reply_enabled = user_settings.get("auto_reply_enabled", False)
    auto_send_enabled = user_settings.get("auto_send_enabled", False)

    # 2. Auto-reply generation
    if auto_reply_enabled and plan_limits.ai_replies:
        seller_name = user_settings.get("seller_name") or (
            user_obj.name if user_obj else "Our Team"
        )
        company_name = (user_obj.company_name if user_obj else None) or "Our Company"
        product_info = user_settings.get("product_info") or ""

        try:
            reply_text = await generate_reply(
                lead_data=lead,
                seller_name=seller_name,
                company_name=company_name,
                product_info=product_info,
            )
            result["auto_reply_generated"] = True
            result["auto_reply_text"] = reply_text
        except Exception:
            logger.exception("AI reply generation failed for user %s", uid)
            reply_text = None

        # 2b. Persist AutoReply row
        lead_id = lead.get("id")
        if reply_text and db is not None and lead_id is not None:
            preferred_channel = user_settings.get("preferred_channel", "email")
            auto_reply = AutoReply(
                user_id=uuid.UUID(uid) if isinstance(user_id, str) else user_id,
                lead_id=uuid.UUID(str(lead_id)) if not isinstance(lead_id, uuid.UUID) else lead_id,
                reply_text=reply_text,
                sent_via=preferred_channel,
                status="pending",
            )
            db.add(auto_reply)
            await db.flush()

            # 2c. Auto-send if enabled
            if auto_send_enabled and reply_text:
                send_result = None
                if preferred_channel == "whatsapp" and lead.get("sender_mobile"):
                    send_result = await send_whatsapp_notification(
                        lead["sender_mobile"], reply_text
                    )
                elif preferred_channel == "email" and lead.get("sender_email"):
                    product = lead.get("query_product_name") or "Your Enquiry"
                    send_result = await send_email_notification(
                        lead["sender_email"],
                        f"Re: {product} — {company_name}",
                        reply_text,
                    )

                if send_result and send_result.success:
                    auto_reply.status = "sent"
                    auto_reply.sent_at = datetime.now(timezone.utc)
                    result["auto_reply_sent"] = True
                elif send_result:
                    auto_reply.status = "failed"
                    logger.warning(
                        "Auto-send failed for lead %s: %s",
                        lead_id,
                        send_result.error,
                    )

            # 2d. Update the Lead row
            if lead_id is not None:
                await db.execute(
                    update(Lead)
                    .where(Lead.id == (uuid.UUID(str(lead_id)) if not isinstance(lead_id, uuid.UUID) else lead_id))
                    .values(
                        ai_reply_text=reply_text,
                        ai_reply_sent=result["auto_reply_sent"],
                        lead_score=lead_score,
                    )
                )

    # Update lead score even if auto-reply is off
    if db is not None and lead.get("id") is not None and not result["auto_reply_generated"]:
        lead_id = lead["id"]
        await db.execute(
            update(Lead)
            .where(Lead.id == (uuid.UUID(str(lead_id)) if not isinstance(lead_id, uuid.UUID) else lead_id))
            .values(lead_score=lead_score)
        )

    # 3. Notify the user
    user_dict: dict[str, Any] = {
        "email": user_obj.email if user_obj else "",
        "phone": user_obj.phone if user_obj else None,
        "name": user_obj.name if user_obj else "",
        "notification_preferences": user_settings.get(
            "notification_preferences", {}
        ),
    }
    try:
        notif_results = await notify_new_lead(user_dict, lead)
        result["notification_results"] = [
            {"channel": r.channel, "success": r.success, "message": r.message}
            for r in notif_results
        ]
    except Exception:
        logger.exception("Notification dispatch failed for user %s", uid)

    return result
