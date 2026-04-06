"""
Lead and sync API endpoints.

All routes require authentication via ``get_current_active_user``.
Mounted under ``/api`` by the main FastAPI application.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from saas.auth import get_current_active_user
from saas.database import async_session_factory
from saas.models import SyncLog, User
from saas.services.lead_service import (
    add_lead_note,
    export_user_leads_csv,
    get_lead_by_id,
    get_user_leads,
    get_user_stats,
    mark_lead_read,
    search_user_leads,
    star_lead,
)
from saas.services.scheduler import (
    get_scheduler_status,
    trigger_manual_sync,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["leads"])


# ─── Request / Response Schemas ──────────────────────────────────────────────


class NoteRequest(BaseModel):
    """Body for adding a note to a lead."""

    note: str = Field(..., min_length=1, max_length=5000)


class SyncResponse(BaseModel):
    """Response after triggering a manual sync."""

    success: bool
    fetched: int = 0
    saved: int = 0
    skipped: int = 0
    errors: list[str] = []


class MessageResponse(BaseModel):
    """Generic message response."""

    message: str
    success: bool = True


# ─── Dependency shorthand ────────────────────────────────────────────────────


CurrentUser = Depends(get_current_active_user)


# ─── Lead Endpoints ─────────────────────────────────────────────────────────


@router.get("/leads/stats")
async def leads_stats(user: User = CurrentUser) -> dict[str, Any]:
    """Dashboard statistics for the authenticated user."""
    return await get_user_stats(user.id)


@router.get("/leads/export")
async def leads_export(
    city: Optional[str] = Query(None),
    product: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    starred: Optional[bool] = Query(None),
    unread: Optional[bool] = Query(None),
    user: User = CurrentUser,
) -> StreamingResponse:
    """Export leads as a CSV file download."""
    filters = _collect_filters(
        city=city,
        product=product,
        date_from=date_from,
        date_to=date_to,
        search=search,
        starred=starred,
        unread=unread,
    )
    csv_content = await export_user_leads_csv(user.id, filters)

    filename = f"leads_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/leads/{lead_id}")
async def lead_detail(
    lead_id: uuid.UUID,
    user: User = CurrentUser,
) -> dict[str, Any]:
    """Get a single lead by ID."""
    lead = await get_lead_by_id(user.id, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.get("/leads")
async def leads_list(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    city: Optional[str] = Query(None),
    product: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    starred: Optional[bool] = Query(None),
    unread: Optional[bool] = Query(None),
    query_type: Optional[str] = Query(None),
    user: User = CurrentUser,
) -> dict[str, Any]:
    """Paginated, filterable lead list."""
    filters = _collect_filters(
        city=city,
        product=product,
        date_from=date_from,
        date_to=date_to,
        search=search,
        starred=starred,
        unread=unread,
        query_type=query_type,
    )
    return await get_user_leads(user.id, page, per_page, filters)


@router.post("/leads/sync", response_model=SyncResponse)
async def leads_sync(user: User = CurrentUser) -> SyncResponse:
    """Trigger an immediate manual sync for the authenticated user."""
    if not user.indiamart_api_key:
        raise HTTPException(
            status_code=400,
            detail="No IndiaMART API key configured. Go to Settings to add one.",
        )

    result = await trigger_manual_sync(user.id)
    return SyncResponse(
        success=result.success,
        fetched=result.fetched,
        saved=result.saved,
        skipped=result.skipped,
        errors=result.errors,
    )


@router.put("/leads/{lead_id}/read", response_model=MessageResponse)
async def lead_mark_read(
    lead_id: uuid.UUID,
    user: User = CurrentUser,
) -> MessageResponse:
    """Mark a lead as read."""
    updated = await mark_lead_read(user.id, lead_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Lead not found")
    return MessageResponse(message="Lead marked as read")


@router.put("/leads/{lead_id}/star")
async def lead_toggle_star(
    lead_id: uuid.UUID,
    user: User = CurrentUser,
) -> dict[str, Any]:
    """Toggle a lead's starred status."""
    new_value = await star_lead(user.id, lead_id)
    if new_value is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"success": True, "is_starred": new_value}


@router.put("/leads/{lead_id}/note", response_model=MessageResponse)
async def lead_add_note(
    lead_id: uuid.UUID,
    body: NoteRequest,
    user: User = CurrentUser,
) -> MessageResponse:
    """Add or update a note on a lead."""
    updated = await add_lead_note(user.id, lead_id, body.note)
    if not updated:
        raise HTTPException(status_code=404, detail="Lead not found")
    return MessageResponse(message="Note saved")


# ─── Sync / Scheduler Endpoints ─────────────────────────────────────────────


@router.get("/sync/logs")
async def sync_logs(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: User = CurrentUser,
) -> dict[str, Any]:
    """Paginated sync history for the authenticated user."""
    offset = (page - 1) * per_page

    async with async_session_factory() as session:
        from sqlalchemy import func

        total = (
            await session.execute(
                select(func.count())
                .select_from(SyncLog)
                .where(SyncLog.user_id == user.id)
            )
        ).scalar() or 0

        rows = (
            await session.execute(
                select(SyncLog)
                .where(SyncLog.user_id == user.id)
                .order_by(SyncLog.synced_at.desc())
                .offset(offset)
                .limit(per_page)
            )
        ).scalars().all()

    logs = [
        {
            "id": str(log.id),
            "sync_type": log.sync_type,
            "leads_fetched": log.leads_fetched,
            "leads_saved": log.leads_saved,
            "status": log.status,
            "error_message": log.error_message,
            "synced_at": log.synced_at.isoformat() if log.synced_at else None,
        }
        for log in rows
    ]

    return {
        "logs": logs,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max((total + per_page - 1) // per_page, 1),
    }


@router.get("/sync/status")
async def sync_status(user: User = CurrentUser) -> dict[str, Any]:
    """Current scheduler status and running jobs."""
    return get_scheduler_status()


@router.get("/leads/{lead_id}/ai-insights")
async def lead_ai_insights(
    lead_id: uuid.UUID,
    user: User = CurrentUser,
) -> dict[str, Any]:
    """Return AI-powered insights for a lead based on heuristic analysis.

    Analyses the lead's query message, company name, and product query to
    generate buying intent score, urgency, budget indicators, personality
    type, negotiation tips, and a suggested outreach approach.

    Args:
        lead_id: UUID of the lead.
        user: Authenticated user (must own the lead).

    Returns:
        Dict with AI insight fields.

    Raises:
        HTTPException 404: If the lead is not found.
    """
    lead = await get_lead_by_id(user.id, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Gather text corpus for analysis
    corpus = " ".join(
        filter(None, [
            lead.get("query_message", ""),
            lead.get("sender_company", ""),
            lead.get("query_product_name", ""),
            lead.get("subject", ""),
        ])
    ).lower()

    insights = _generate_ai_insights(corpus, lead)
    return insights


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _collect_filters(**kwargs: Any) -> dict[str, Any]:
    """Build a filters dict, dropping ``None`` values."""
    return {k: v for k, v in kwargs.items() if v is not None}


def _generate_ai_insights(corpus: str, lead: dict[str, Any]) -> dict[str, Any]:
    """Generate mock AI insights via keyword-based heuristics.

    Args:
        corpus: Lowercased combined text from the lead's message and metadata.
        lead: Full lead dict.

    Returns:
        AI insight dict with buying intent, urgency, budget, personality, and tips.
    """
    # ── Buying Intent (0–100) ────────────────────────────────────────────────
    intent_score = 30  # baseline
    high_intent_keywords = [
        "urgent", "immediately", "asap", "today", "now", "quick", "fast",
        "bulk", "large quantity", "order", "purchase", "buy", "need",
        "quote", "price", "best price", "sample", "demo",
    ]
    medium_intent_keywords = [
        "interested", "enquiry", "inquiry", "information", "details",
        "catalogue", "catalog", "brochure", "specification", "specs",
    ]
    for kw in high_intent_keywords:
        if kw in corpus:
            intent_score += 8
    for kw in medium_intent_keywords:
        if kw in corpus:
            intent_score += 4
    intent_score = min(intent_score, 100)

    # ── Urgency ──────────────────────────────────────────────────────────────
    if any(kw in corpus for kw in ["urgent", "asap", "immediately", "today", "now", "quick", "fast"]):
        urgency = "high"
    elif any(kw in corpus for kw in ["soon", "week", "shortly", "need by"]):
        urgency = "medium"
    else:
        urgency = "low"

    # ── Budget Indicator ─────────────────────────────────────────────────────
    high_budget_signals = ["best quality", "premium", "top brand", "no compromise", "enterprise"]
    low_budget_signals = ["cheapest", "lowest price", "cheap", "affordable", "budget", "economical"]
    if any(kw in corpus for kw in high_budget_signals):
        budget_indicator = "high"
    elif any(kw in corpus for kw in low_budget_signals):
        budget_indicator = "low"
    else:
        budget_indicator = "medium"

    # ── Personality Type ─────────────────────────────────────────────────────
    analytical_signals = ["specification", "specs", "technical", "data", "details", "comparison"]
    driver_signals = ["decision", "decide", "ceo", "director", "owner", "manager", "head"]
    expressive_signals = ["great", "amazing", "wonderful", "excited", "love", "fantastic"]
    if any(kw in corpus for kw in analytical_signals):
        personality_type = "analytical"
    elif any(kw in corpus for kw in driver_signals):
        personality_type = "driver"
    elif any(kw in corpus for kw in expressive_signals):
        personality_type = "expressive"
    else:
        personality_type = "amiable"

    # ── Competitor Mentions ──────────────────────────────────────────────────
    common_competitor_keywords = [
        "amazon", "flipkart", "alibaba", "indiamart", "tradeindia",
        "justdial", "local supplier", "other supplier", "another vendor",
    ]
    competitor_mentions = [kw for kw in common_competitor_keywords if kw in corpus]

    # ── Negotiation Tips ─────────────────────────────────────────────────────
    negotiation_tips = []
    if budget_indicator == "low":
        negotiation_tips.append("Offer volume discount or payment terms to close the deal")
        negotiation_tips.append("Highlight value-for-money and ROI over raw price")
    if urgency == "high":
        negotiation_tips.append("Emphasise quick delivery and availability — this buyer is time-sensitive")
    if competitor_mentions:
        negotiation_tips.append("Differentiate on quality, support, or warranty vs competitors mentioned")
    if personality_type == "analytical":
        negotiation_tips.append("Lead with data, specs, and case studies rather than soft sells")
    if personality_type == "driver":
        negotiation_tips.append("Be direct, concise, and focus on outcomes — they decide fast")
    if not negotiation_tips:
        negotiation_tips.append("Build rapport first; ask about their use case before pitching")
        negotiation_tips.append("Follow up within 24 hours to maintain momentum")

    # ── Suggested Approach ───────────────────────────────────────────────────
    approach_map = {
        ("high", "high"): "Call immediately with a ready quotation — high intent, high urgency. Don't delay.",
        ("high", "medium"): "Send a personalised quote today and schedule a call for follow-up.",
        ("high", "low"): "Send a detailed product catalogue and nurture with value-focused content.",
        ("medium", "high"): "Reach out via WhatsApp/call — there's urgency but moderate intent, qualify quickly.",
        ("medium", "medium"): "Email with product highlights and ask for a call to understand requirements.",
        ("medium", "low"): "Add to drip campaign; check in weekly with relevant content.",
        ("low", "high"): "Qualify via a quick call — urgency exists but intent is unclear.",
        ("low", "medium"): "Send an introductory email and follow up in 3–5 days.",
        ("low", "low"): "Place in long-term nurture; focus on higher-intent leads first.",
    }
    intent_bucket = "high" if intent_score >= 65 else ("medium" if intent_score >= 40 else "low")
    suggested_approach = approach_map.get(
        (intent_bucket, urgency),
        "Engage with a personalised message to understand the buyer's needs.",
    )

    return {
        "buying_intent": intent_score,
        "urgency": urgency,
        "budget_indicator": budget_indicator,
        "personality_type": personality_type,
        "negotiation_tips": negotiation_tips,
        "suggested_approach": suggested_approach,
        "competitor_mentions": competitor_mentions,
    }
