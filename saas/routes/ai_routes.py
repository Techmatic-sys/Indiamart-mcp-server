"""
AI API Routes — reply generation, lead scoring, digest, and settings.

All endpoints require JWT authentication and are scoped to the current tenant.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from saas.auth import get_current_active_user
from saas.database import get_db
from saas.models import AutoReply, Lead, User
from saas.services.ai_service import (
    categorize_lead,
    generate_daily_digest,
    generate_reply,
    score_lead,
)
from saas.services.auto_reply_service import (
    get_user_auto_reply_settings,
    update_auto_reply_settings,
)
from saas.services.notification_service import (
    send_email_notification,
    send_whatsapp_notification,
)

router = APIRouter(prefix="/api/ai", tags=["AI"])


# ─── Pydantic schemas ───────────────────────────────────────────────────────


class ReplyResponse(BaseModel):
    lead_id: str
    reply_text: str
    score: int
    category: str


class ScoreResponse(BaseModel):
    lead_id: str
    score: int
    category: str


class DigestResponse(BaseModel):
    digest: str
    total_leads: int


class AutoReplySettingsSchema(BaseModel):
    auto_reply_enabled: bool = False
    auto_send_enabled: bool = False
    preferred_channel: str = "email"
    product_info: str = ""
    seller_name: str = ""
    notification_preferences: dict[str, Any] = Field(
        default_factory=lambda: {
            "email_enabled": True,
            "whatsapp_enabled": False,
        }
    )


class AutoReplyRecord(BaseModel):
    id: str
    lead_id: str
    reply_text: str
    sent_via: str
    status: str
    sent_at: Optional[str] = None
    created_at: str


class SendReplyResponse(BaseModel):
    success: bool
    message: str
    sent_via: str


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _lead_to_dict(lead: Lead) -> dict[str, Any]:
    """Convert a Lead ORM instance to a plain dict for service functions."""
    return {
        "id": lead.id,
        "sender_name": lead.sender_name,
        "sender_mobile": lead.sender_mobile,
        "sender_email": lead.sender_email,
        "sender_company": lead.sender_company,
        "sender_address": lead.sender_address,
        "sender_city": lead.sender_city,
        "sender_pincode": lead.sender_pincode,
        "query_product_name": lead.query_product_name,
        "query_message": lead.query_message,
        "query_type": lead.query_type,
        "ai_reply_sent": lead.ai_reply_sent,
    }


async def _get_user_lead(
    lead_id: str,
    user: User,
    db: AsyncSession,
) -> Lead:
    """Fetch a lead owned by the current user or raise 404."""
    try:
        lid = uuid.UUID(lead_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid lead ID format.")

    result = await db.execute(
        select(Lead).where(Lead.id == lid, Lead.user_id == user.id)
    )
    lead = result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found.")
    return lead


# ─── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/reply/{lead_id}", response_model=ReplyResponse)
async def generate_ai_reply(
    lead_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ReplyResponse:
    """Generate an AI-powered reply draft for a lead (does **not** send it).

    The reply is saved to the ``auto_replies`` table with status ``"pending"``.
    """
    lead = await _get_user_lead(lead_id, user, db)
    lead_data = _lead_to_dict(lead)

    # Gather settings
    settings = await get_user_auto_reply_settings(str(user.id))
    seller_name = settings.get("seller_name") or user.name
    company_name = user.company_name or "Our Company"
    product_info = settings.get("product_info") or ""

    # Generate
    reply_text = await generate_reply(lead_data, seller_name, company_name, product_info)
    lead_score = score_lead(lead_data)
    category = categorize_lead(lead_data)

    # Persist auto-reply record
    auto_reply = AutoReply(
        user_id=user.id,
        lead_id=lead.id,
        reply_text=reply_text,
        sent_via=settings.get("preferred_channel", "email"),
        status="pending",
    )
    db.add(auto_reply)

    # Update lead score & reply text
    await db.execute(
        update(Lead)
        .where(Lead.id == lead.id)
        .values(ai_reply_text=reply_text, lead_score=lead_score)
    )
    await db.flush()

    return ReplyResponse(
        lead_id=str(lead.id),
        reply_text=reply_text,
        score=lead_score,
        category=category,
    )


@router.post("/reply/{lead_id}/send", response_model=SendReplyResponse)
async def send_ai_reply(
    lead_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> SendReplyResponse:
    """Send the most recent pending AI reply for a lead.

    Looks up the latest ``pending`` AutoReply record for this lead and
    delivers it via the configured channel (email or WhatsApp).
    """
    lead = await _get_user_lead(lead_id, user, db)

    # Find latest pending reply
    result = await db.execute(
        select(AutoReply)
        .where(
            AutoReply.lead_id == lead.id,
            AutoReply.user_id == user.id,
            AutoReply.status == "pending",
        )
        .order_by(AutoReply.created_at.desc())
        .limit(1)
    )
    auto_reply = result.scalar_one_or_none()
    if auto_reply is None:
        raise HTTPException(
            status_code=404,
            detail="No pending AI reply found for this lead. Generate one first.",
        )

    # Send via preferred channel
    settings = await get_user_auto_reply_settings(str(user.id))
    channel = settings.get("preferred_channel", "email")
    send_result = None

    if channel == "whatsapp" and lead.sender_mobile:
        send_result = await send_whatsapp_notification(
            lead.sender_mobile, auto_reply.reply_text
        )
    elif lead.sender_email:
        product = lead.query_product_name or "Your Enquiry"
        company = user.company_name or "Our Company"
        send_result = await send_email_notification(
            lead.sender_email,
            f"Re: {product} — {company}",
            auto_reply.reply_text,
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=f"No contact info available for channel '{channel}'.",
        )

    if send_result and send_result.success:
        auto_reply.status = "sent"
        auto_reply.sent_at = datetime.now(timezone.utc)
        await db.execute(
            update(Lead)
            .where(Lead.id == lead.id)
            .values(ai_reply_sent=True)
        )
        return SendReplyResponse(
            success=True,
            message=f"Reply sent to {lead.sender_email or lead.sender_mobile}",
            sent_via=channel,
        )

    auto_reply.status = "failed"
    error_msg = send_result.error if send_result else "Unknown error"
    raise HTTPException(
        status_code=502,
        detail=f"Failed to send reply: {error_msg}",
    )


@router.get("/score/{lead_id}", response_model=ScoreResponse)
async def get_lead_score(
    lead_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ScoreResponse:
    """Calculate (or recalculate) the quality score for a lead."""
    lead = await _get_user_lead(lead_id, user, db)
    lead_data = _lead_to_dict(lead)

    lead_score = score_lead(lead_data)
    category = categorize_lead(lead_data)

    # Persist score
    await db.execute(
        update(Lead).where(Lead.id == lead.id).values(lead_score=lead_score)
    )

    return ScoreResponse(
        lead_id=str(lead.id),
        score=lead_score,
        category=category,
    )


@router.post("/digest", response_model=DigestResponse)
async def create_daily_digest(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> DigestResponse:
    """Generate a daily digest for the authenticated user's leads received today."""
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    result = await db.execute(
        select(Lead).where(
            Lead.user_id == user.id,
            Lead.created_at >= today_start,
        )
    )
    leads = result.scalars().all()
    leads_dicts = [_lead_to_dict(lead) for lead in leads]

    digest = generate_daily_digest(str(user.id), leads_dicts)

    return DigestResponse(digest=digest, total_leads=len(leads_dicts))


@router.get("/settings", response_model=AutoReplySettingsSchema)
async def get_ai_settings(
    user: User = Depends(get_current_active_user),
) -> AutoReplySettingsSchema:
    """Get the current user's auto-reply and notification settings."""
    settings = await get_user_auto_reply_settings(str(user.id))
    return AutoReplySettingsSchema(**settings)


@router.put("/settings", response_model=AutoReplySettingsSchema)
async def update_ai_settings(
    payload: AutoReplySettingsSchema,
    user: User = Depends(get_current_active_user),
) -> AutoReplySettingsSchema:
    """Update the current user's auto-reply and notification settings."""
    await update_auto_reply_settings(str(user.id), payload.model_dump())
    updated = await get_user_auto_reply_settings(str(user.id))
    return AutoReplySettingsSchema(**updated)


@router.get("/replies", response_model=list[AutoReplyRecord])
async def list_ai_replies(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> list[AutoReplyRecord]:
    """List all AI-generated replies for the authenticated user."""
    result = await db.execute(
        select(AutoReply)
        .where(AutoReply.user_id == user.id)
        .order_by(AutoReply.created_at.desc())
    )
    replies = result.scalars().all()

    return [
        AutoReplyRecord(
            id=str(r.id),
            lead_id=str(r.lead_id),
            reply_text=r.reply_text,
            sent_via=r.sent_via,
            status=r.status,
            sent_at=r.sent_at.isoformat() if r.sent_at else None,
            created_at=r.created_at.isoformat(),
        )
        for r in replies
    ]
