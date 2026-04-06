"""
Pipeline, Activity, Notification, Reminder, and AI Insights API routes.

Provides endpoints for:
- Kanban pipeline (stage changes, deal values)
- Activity timeline per lead
- Notification center
- Follow-up reminders
- AI lead insights (mock/template based)
- Bulk actions on leads
"""

from __future__ import annotations

import logging
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from saas.auth import get_current_active_user
from saas.database import get_db
from saas.models import Activity, Lead, Notification, Reminder, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Pipeline"])


# ─── Request / Response Schemas ──────────────────────────────────────────────


class StageUpdateRequest(BaseModel):
    stage: str = Field(..., pattern=r"^(new|contacted|qualified|proposal|negotiation|won|lost)$")


class DealValueRequest(BaseModel):
    deal_value: float = Field(..., ge=0)


class ActivityCreate(BaseModel):
    activity_type: str = Field(..., pattern=r"^(note|call|email|whatsapp|meeting|stage_change)$")
    content: str = Field(..., min_length=1, max_length=5000)


class ReminderCreate(BaseModel):
    lead_id: str
    message: str = Field(..., min_length=1, max_length=1000)
    remind_at: datetime


class ReminderUpdate(BaseModel):
    is_done: Optional[bool] = None
    message: Optional[str] = None
    remind_at: Optional[datetime] = None


class BulkStageRequest(BaseModel):
    lead_ids: list[str]
    stage: str = Field(..., pattern=r"^(new|contacted|qualified|proposal|negotiation|won|lost)$")


class BulkDeleteRequest(BaseModel):
    lead_ids: list[str]


# ─── Pipeline / Stage Endpoints ──────────────────────────────────────────────


@router.put("/leads/{lead_id}/stage")
async def update_lead_stage(
    lead_id: uuid.UUID,
    body: StageUpdateRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Update a lead's pipeline stage."""
    result = await db.execute(
        select(Lead).where(Lead.id == lead_id, Lead.user_id == user.id)
    )
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    old_stage = lead.lead_stage
    lead.lead_stage = body.stage

    # Auto-create stage change activity
    activity = Activity(
        lead_id=str(lead_id),
        user_id=str(user.id),
        activity_type="stage_change",
        content=f"Stage changed from '{old_stage}' to '{body.stage}'"
    )
    db.add(activity)

    await db.flush()
    return {"success": True, "lead_id": str(lead_id), "stage": body.stage, "old_stage": old_stage}


@router.put("/leads/{lead_id}/deal-value")
async def update_deal_value(
    lead_id: uuid.UUID,
    body: DealValueRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Update a lead's deal value."""
    result = await db.execute(
        update(Lead)
        .where(Lead.id == lead_id, Lead.user_id == user.id)
        .values(deal_value=body.deal_value)
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"success": True, "lead_id": str(lead_id), "deal_value": body.deal_value}


@router.get("/leads/pipeline")
async def get_pipeline(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get all leads grouped by pipeline stage with counts and values."""
    stages = ["new", "contacted", "qualified", "proposal", "negotiation", "won", "lost"]
    pipeline = {}

    for stage in stages:
        result = await db.execute(
            select(Lead)
            .where(Lead.user_id == user.id, Lead.lead_stage == stage)
            .order_by(Lead.created_at.desc())
        )
        leads = result.scalars().all()

        total_value = sum(l.deal_value or 0 for l in leads)
        pipeline[stage] = {
            "leads": [
                {
                    "id": str(l.id),
                    "sender_name": l.sender_name,
                    "sender_company": l.sender_company,
                    "query_product_name": l.query_product_name,
                    "sender_city": l.sender_city,
                    "lead_score": l.lead_score,
                    "deal_value": l.deal_value,
                    "sender_mobile": l.sender_mobile,
                    "sender_email": l.sender_email,
                    "query_time": l.query_time.isoformat() if l.query_time else None,
                    "created_at": l.created_at.isoformat() if l.created_at else None,
                }
                for l in leads
            ],
            "count": len(leads),
            "total_value": total_value,
        }

    # Summary stats
    total_deals = sum(p["total_value"] for p in pipeline.values())
    won_value = pipeline["won"]["total_value"]

    return {
        "pipeline": pipeline,
        "summary": {
            "total_leads": sum(p["count"] for p in pipeline.values()),
            "total_pipeline_value": total_deals,
            "won_value": won_value,
            "stages": stages,
        },
    }


# ─── Activity Timeline ──────────────────────────────────────────────────────


@router.post("/leads/{lead_id}/activities")
async def create_activity(
    lead_id: uuid.UUID,
    body: ActivityCreate,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Add an activity entry to a lead's timeline."""
    # Verify lead belongs to user
    result = await db.execute(
        select(Lead).where(Lead.id == lead_id, Lead.user_id == user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Lead not found")

    activity = Activity(
        lead_id=str(lead_id),
        user_id=str(user.id),
        activity_type=body.activity_type,
        content=body.content,
    )
    db.add(activity)
    await db.flush()
    await db.refresh(activity)

    return {
        "id": str(activity.id),
        "lead_id": str(lead_id),
        "activity_type": activity.activity_type,
        "content": activity.content,
        "created_at": activity.created_at.isoformat() if activity.created_at else None,
    }


@router.get("/leads/{lead_id}/activities")
async def get_activities(
    lead_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get all activities for a lead, newest first."""
    # Verify lead belongs to user
    result = await db.execute(
        select(Lead).where(Lead.id == lead_id, Lead.user_id == user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Lead not found")

    result = await db.execute(
        select(Activity)
        .where(Activity.lead_id == lead_id)
        .order_by(Activity.created_at.desc())
    )
    activities = result.scalars().all()

    return {
        "activities": [
            {
                "id": str(a.id),
                "activity_type": a.activity_type,
                "content": a.content,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in activities
        ],
        "total": len(activities),
    }


# ─── AI Lead Insights (Template/Mock Based) ─────────────────────────────────


@router.get("/leads/{lead_id}/ai-insights")
async def get_ai_insights(
    lead_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Generate AI insights for a lead (template-based analysis)."""
    result = await db.execute(
        select(Lead).where(Lead.id == lead_id, Lead.user_id == user.id)
    )
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Compute insights based on lead data
    score = lead.lead_score or 50
    has_phone = bool(lead.sender_mobile)
    has_email = bool(lead.sender_email)
    has_company = bool(lead.sender_company)
    message_len = len(lead.query_message or "")
    query_type = (lead.query_type or "").upper()

    # Buying intent analysis
    if score >= 70:
        buying_intent = {"level": "High", "score": random.randint(75, 95), "description": "This lead shows strong buying signals with detailed contact info and specific product interest."}
    elif score >= 40:
        buying_intent = {"level": "Medium", "score": random.randint(45, 74), "description": "Moderate interest detected. Lead is exploring options and comparing suppliers."}
    else:
        buying_intent = {"level": "Low", "score": random.randint(15, 44), "description": "Early-stage enquiry. Lead may be doing initial research or price comparison."}

    # Urgency indicators
    urgency_signals = []
    if query_type == "B":
        urgency_signals.append("Buy Lead — direct purchase intent")
    if message_len > 100:
        urgency_signals.append("Detailed message indicates serious interest")
    if has_phone and has_email:
        urgency_signals.append("Multiple contact channels provided")
    if lead.sender_pincode:
        urgency_signals.append("Pin code shared — ready for delivery")
    urgency = "High" if len(urgency_signals) >= 3 else "Medium" if len(urgency_signals) >= 1 else "Low"

    # Budget indicators
    budget_signals = []
    if has_company:
        budget_signals.append("Business buyer (company name provided)")
    if lead.sender_city and lead.sender_city.lower() in ["mumbai", "delhi", "bangalore", "hyderabad", "chennai", "pune", "kolkata", "ahmedabad"]:
        budget_signals.append(f"Metro city ({lead.sender_city}) — typically higher budget")
    if query_type == "B":
        budget_signals.append("Direct buy lead — budget likely allocated")

    # Personality type (fun mock)
    personality_types = [
        {"type": "The Decisive Buyer", "emoji": "🎯", "description": "Quick decision maker. Present clear pricing and fast delivery options."},
        {"type": "The Researcher", "emoji": "🔍", "description": "Likes comparing options. Provide detailed specs, testimonials, and competitive advantages."},
        {"type": "The Negotiator", "emoji": "🤝", "description": "Will push for better deals. Have room for discount but lead with value proposition."},
        {"type": "The Relationship Builder", "emoji": "💼", "description": "Values long-term partnerships. Focus on service quality and reliability."},
    ]
    # Deterministic selection based on lead data
    persona_idx = (len(lead.sender_name or "") + len(lead.query_product_name or "")) % len(personality_types)
    personality = personality_types[persona_idx]

    # Negotiation tips
    tips = []
    if score >= 70:
        tips = [
            "Strike while the iron is hot — respond within 1 hour",
            f"Mention their specific product interest: {lead.query_product_name or 'their enquiry'}",
            "Offer a time-limited introductory price",
            "Propose a quick call to discuss requirements",
        ]
    elif score >= 40:
        tips = [
            "Build rapport first — ask about their specific requirements",
            "Share 2-3 relevant case studies or testimonials",
            "Offer a free sample or demo if possible",
            "Follow up within 24 hours with a detailed quote",
        ]
    else:
        tips = [
            "Send a catalog with full product range",
            "Add value — share industry insights or guides",
            "Set a follow-up reminder for 3-5 days",
            "Keep communication channels open but don't push too hard",
        ]

    # Suggested next action
    if lead.lead_stage == "new":
        next_action = "Make first contact — call or WhatsApp within 2 hours"
    elif lead.lead_stage == "contacted":
        next_action = "Send detailed product catalog and pricing"
    elif lead.lead_stage == "qualified":
        next_action = "Prepare and send a formal proposal"
    elif lead.lead_stage == "proposal":
        next_action = "Follow up on proposal — address any concerns"
    elif lead.lead_stage == "negotiation":
        next_action = "Finalize terms and close the deal"
    else:
        next_action = "Review lead status and plan next steps"

    # ── Buyer Verification Score ─────────────────────────────────────────
    verification_score = 0
    verification_badges = []
    FREE_EMAIL_DOMAINS = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "rediffmail.com", "ymail.com", "live.com"}
    MAJOR_BUSINESS_CITIES = {
        "mumbai", "delhi", "bangalore", "bengaluru", "hyderabad", "chennai", "pune",
        "kolkata", "ahmedabad", "surat", "jaipur", "lucknow", "kanpur", "nagpur",
        "indore", "thane", "bhopal", "visakhapatnam", "patna", "vadodara",
        "ludhiana", "agra", "nashik", "coimbatore", "rajkot", "meerut", "faridabad",
        "ghaziabad", "noida", "gurugram", "chandigarh", "kochi", "bhubaneswar"
    }

    # +20 valid Indian mobile
    if lead.sender_mobile:
        phone_clean = lead.sender_mobile.replace(" ", "").replace("-", "").lstrip("+").lstrip("91")
        if len(phone_clean) == 10 and phone_clean[0] in "6789":
            verification_score += 20
            verification_badges.append("Valid Phone")

    # +25 business email domain
    if lead.sender_email:
        email_domain = lead.sender_email.split("@")[-1].lower() if "@" in lead.sender_email else ""
        if email_domain and email_domain not in FREE_EMAIL_DOMAINS:
            verification_score += 25
            verification_badges.append("Business Email")

    # +20 company name
    if lead.sender_company and lead.sender_company.strip():
        verification_score += 20
        verification_badges.append("Company Verified")

    # +15 major Indian city
    if lead.sender_city and lead.sender_city.strip().lower() in MAJOR_BUSINESS_CITIES:
        verification_score += 15
        verification_badges.append("Verified City")

    # +20 message length > 50
    if message_len > 50:
        verification_score += 20
        verification_badges.append("Detailed Enquiry")

    # ── Competitor Intelligence ──────────────────────────────────────────
    COMPETITOR_KEYWORDS = {
        "alibaba": "Alibaba", "tradeindia": "TradeIndia", "justdial": "JustDial",
        "amazon": "Amazon", "flipkart": "Flipkart", "made-in-china": "Made-in-China",
        "cheaper": "Price Comparison", "compare": "Supplier Comparison",
        "alternative": "Alternative Supplier", "other supplier": "Other Supplier",
        "better price": "Price Negotiation", "quotation from": "Multiple Quotes",
        "indiamart": "IndiaMart (competitor ref)", "exportersindia": "ExportersIndia",
        "sulekha": "Sulekha", "shopclues": "ShopClues", "snapdeal": "Snapdeal",
    }
    msg_lower = (lead.query_message or "").lower()
    competitor_mentions = []
    for kw, name in COMPETITOR_KEYWORDS.items():
        if kw in msg_lower:
            idx = msg_lower.find(kw)
            start = max(0, idx - 30)
            end = min(len(lead.query_message or ""), idx + len(kw) + 30)
            snippet = (lead.query_message or "")[start:end].strip()
            competitor_mentions.append({"name": name, "context_snippet": f"...{snippet}..."})

    if len(competitor_mentions) >= 3:
        competitive_risk = "high"
    elif len(competitor_mentions) >= 1:
        competitive_risk = "medium"
    else:
        competitive_risk = "low"

    battlecard_tips = []
    if competitive_risk == "high":
        battlecard_tips = [
            "They're actively comparing — send your USP summary immediately",
            "Emphasize quality certifications, delivery reliability, and after-sales support",
            "Offer a reference customer call or testimonial from a similar business",
            "Consider a time-limited introductory offer to accelerate decision",
        ]
    elif competitive_risk == "medium":
        battlecard_tips = [
            "They mentioned price comparison — emphasize quality and after-sales service",
            "Share case studies showing ROI and long-term value over cheap alternatives",
            "Highlight your after-sales support and warranty policy",
        ]
    else:
        battlecard_tips = [
            "No competitor signals — focus on building trust and demonstrating product fit",
            "Share your catalog and let product quality speak for itself",
        ]

    # ── Churn Prediction ─────────────────────────────────────────────────
    now_utc = datetime.now(timezone.utc)
    last_activity_date = lead.created_at
    # Use created_at as baseline; days since lead creation is a proxy for stagnation
    created_aware = lead.created_at.replace(tzinfo=timezone.utc) if lead.created_at and lead.created_at.tzinfo is None else lead.created_at
    days_since_created = (now_utc - created_aware).days if created_aware else 0

    churn_probability = 0
    rescue_action = "Continue nurturing the lead with valuable content"

    # Stage stagnation signal (early stages that haven't moved = risk)
    STALE_STAGE_RISK = {"new": 3, "contacted": 7, "qualified": 10, "proposal": 14, "negotiation": 21}
    stage_threshold = STALE_STAGE_RISK.get(lead.lead_stage, 30)
    if days_since_created > stage_threshold:
        excess_days = days_since_created - stage_threshold
        churn_probability = min(90, 30 + excess_days * 5)

    # Response time signal
    if lead.response_time_mins and lead.response_time_mins > 240:  # > 4 hours
        churn_probability = min(95, churn_probability + 15)

    # Message urgency boost (urgent messages that weren't acted on = risk)
    urgent_words = ["urgent", "immediately", "asap", "quickly", "today", "right away"]
    if any(w in msg_lower for w in urgent_words) and days_since_created > 2:
        churn_probability = min(95, churn_probability + 20)

    if churn_probability >= 60:
        churn_risk = "high"
        rescue_action = "Send a personalized discount offer or exclusive bundle today"
    elif churn_probability >= 30:
        churn_risk = "medium"
        rescue_action = "Schedule a follow-up call and share a relevant case study"
    else:
        churn_risk = "low"
        rescue_action = "Keep nurturing — respond promptly to any new messages"

    # ── Best Time to Contact ─────────────────────────────────────────────
    MANUFACTURING_CITIES = {
        "ludhiana", "coimbatore", "rajkot", "surat", "tiruppur", "moradabad",
        "aligarh", "agra", "kanpur", "meerut", "jalandhar", "amritsar",
        "batala", "firozabad", "khurja", "saharanpur"
    }
    METRO_CITIES = {
        "mumbai", "delhi", "bangalore", "bengaluru", "hyderabad", "chennai",
        "kolkata", "pune", "ahmedabad", "noida", "gurugram", "ghaziabad", "thane"
    }
    city_lower = (lead.sender_city or "").strip().lower()
    if city_lower in MANUFACTURING_CITIES:
        best_call_time = "10:00 AM - 12:00 PM"
        contact_reason = f"{lead.sender_city} is a manufacturing hub — business owners are available in late morning"
    elif city_lower in METRO_CITIES:
        best_call_time = "2:00 PM - 4:00 PM"
        contact_reason = f"{lead.sender_city} metro — corporate buyers are free post-lunch"
    elif city_lower:
        best_call_time = "11:00 AM - 1:00 PM"
        contact_reason = "Mid-morning works best for most Indian cities"
    else:
        best_call_time = "10:00 AM - 12:00 PM"
        contact_reason = "Default Indian business hours"

    return {
        "lead_id": str(lead_id),
        "buying_intent": buying_intent,
        "urgency": {
            "level": urgency,
            "signals": urgency_signals,
        },
        "budget_indicators": budget_signals,
        "personality": personality,
        "negotiation_tips": tips,
        "suggested_next_action": next_action,
        "recommended_channel": "phone" if has_phone else "email" if has_email else "platform",
        # Enhanced sections
        "buyer_verification": {
            "verification_score": verification_score,
            "verification_badges": verification_badges,
            "summary": (
                "High-confidence business buyer" if verification_score >= 75
                else "Moderate confidence — verify before investing heavy time" if verification_score >= 45
                else "Low-confidence lead — prioritize verified leads first"
            ),
        },
        "competitor_intelligence": {
            "competitor_mentions": competitor_mentions,
            "competitive_risk": competitive_risk,
            "battlecard_tips": battlecard_tips,
        },
        "churn_prediction": {
            "churn_risk": churn_risk,
            "churn_probability": churn_probability,
            "days_since_created": days_since_created,
            "rescue_action": rescue_action,
        },
        "best_time_to_contact": {
            "best_call_time": best_call_time,
            "timezone": "IST",
            "reason": contact_reason,
        },
    }


# ─── Notification Center ────────────────────────────────────────────────────


@router.get("/notifications")
async def get_notifications(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    unread_only: bool = Query(False),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get user notifications with optional unread filter."""
    conditions = [Notification.user_id == user.id]
    if unread_only:
        conditions.append(Notification.is_read == False)

    total = (await db.execute(
        select(func.count()).select_from(Notification).where(and_(*conditions))
    )).scalar() or 0

    unread_count = (await db.execute(
        select(func.count()).select_from(Notification)
        .where(Notification.user_id == user.id, Notification.is_read == False)
    )).scalar() or 0

    offset = (page - 1) * per_page
    result = await db.execute(
        select(Notification)
        .where(and_(*conditions))
        .order_by(Notification.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    notifications = result.scalars().all()

    return {
        "notifications": [
            {
                "id": str(n.id),
                "title": n.title,
                "message": n.message,
                "type": n.notification_type,
                "is_read": n.is_read,
                "link": n.link,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in notifications
        ],
        "total": total,
        "unread_count": unread_count,
    }


@router.put("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Mark a notification as read."""
    result = await db.execute(
        update(Notification)
        .where(Notification.id == notification_id, Notification.user_id == user.id)
        .values(is_read=True)
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"success": True}


@router.put("/notifications/read-all")
async def mark_all_notifications_read(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Mark all notifications as read."""
    await db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.is_read == False)
        .values(is_read=True)
    )
    return {"success": True}


# ─── Reminders ───────────────────────────────────────────────────────────────


@router.post("/reminders")
async def create_reminder(
    body: ReminderCreate,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a follow-up reminder for a lead."""
    # Verify lead
    result = await db.execute(
        select(Lead).where(Lead.id == body.lead_id, Lead.user_id == user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Lead not found")

    reminder = Reminder(
        lead_id=body.lead_id,
        user_id=str(user.id),
        message=body.message,
        remind_at=body.remind_at,
    )
    db.add(reminder)
    await db.flush()
    await db.refresh(reminder)

    return {
        "id": str(reminder.id),
        "lead_id": body.lead_id,
        "message": reminder.message,
        "remind_at": reminder.remind_at.isoformat(),
        "is_done": reminder.is_done,
    }


@router.get("/reminders")
async def list_reminders(
    include_done: bool = Query(False),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List all reminders for the user, with lead info."""
    conditions = [Reminder.user_id == user.id]
    if not include_done:
        conditions.append(Reminder.is_done == False)

    result = await db.execute(
        select(Reminder, Lead.sender_name, Lead.query_product_name)
        .join(Lead, Reminder.lead_id == Lead.id)
        .where(and_(*conditions))
        .order_by(Reminder.remind_at.asc())
    )
    rows = result.all()

    return {
        "reminders": [
            {
                "id": str(r[0].id),
                "lead_id": str(r[0].lead_id),
                "lead_name": r[1] or "Unknown",
                "lead_product": r[2] or "N/A",
                "message": r[0].message,
                "remind_at": r[0].remind_at.isoformat(),
                "is_done": r[0].is_done,
                "created_at": r[0].created_at.isoformat() if r[0].created_at else None,
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.put("/reminders/{reminder_id}")
async def update_reminder(
    reminder_id: uuid.UUID,
    body: ReminderUpdate,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Update a reminder (mark done, change message/time)."""
    updates = {}
    if body.is_done is not None:
        updates["is_done"] = body.is_done
    if body.message is not None:
        updates["message"] = body.message
    if body.remind_at is not None:
        updates["remind_at"] = body.remind_at

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = await db.execute(
        update(Reminder)
        .where(Reminder.id == reminder_id, Reminder.user_id == user.id)
        .values(**updates)
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return {"success": True}


@router.delete("/reminders/{reminder_id}")
async def delete_reminder(
    reminder_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Delete a reminder."""
    result = await db.execute(
        delete(Reminder).where(Reminder.id == reminder_id, Reminder.user_id == user.id)
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return {"success": True}


# ─── Bulk Actions ────────────────────────────────────────────────────────────


@router.put("/leads/bulk/stage")
async def bulk_update_stage(
    body: BulkStageRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Bulk update stage for multiple leads."""
    result = await db.execute(
        update(Lead)
        .where(Lead.id.in_(body.lead_ids), Lead.user_id == user.id)
        .values(lead_stage=body.stage)
    )
    return {"success": True, "updated": result.rowcount, "stage": body.stage}


@router.delete("/leads/bulk/delete")
async def bulk_delete_leads(
    body: BulkDeleteRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Bulk delete leads."""
    result = await db.execute(
        delete(Lead).where(Lead.id.in_(body.lead_ids), Lead.user_id == user.id)
    )
    return {"success": True, "deleted": result.rowcount}


# ─── Enhanced Dashboard Stats ────────────────────────────────────────────────


@router.get("/dashboard/enhanced")
async def enhanced_dashboard(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Enhanced dashboard data with funnel, revenue, hot leads, activities, reminders."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Pipeline funnel counts
    stages = ["new", "contacted", "qualified", "proposal", "negotiation", "won", "lost"]
    funnel = {}
    for stage in stages:
        count = (await db.execute(
            select(func.count()).select_from(Lead)
            .where(Lead.user_id == user.id, Lead.lead_stage == stage)
        )).scalar() or 0
        funnel[stage] = count

    # Revenue summary
    total_pipeline = (await db.execute(
        select(func.coalesce(func.sum(Lead.deal_value), 0))
        .where(Lead.user_id == user.id, Lead.deal_value.isnot(None))
    )).scalar() or 0

    won_revenue = (await db.execute(
        select(func.coalesce(func.sum(Lead.deal_value), 0))
        .where(Lead.user_id == user.id, Lead.lead_stage == "won", Lead.deal_value.isnot(None))
    )).scalar() or 0

    # Hot leads (score >= 70)
    hot_leads_result = await db.execute(
        select(Lead)
        .where(Lead.user_id == user.id, Lead.lead_score >= 70)
        .order_by(Lead.lead_score.desc())
        .limit(5)
    )
    hot_leads = [
        {
            "id": str(l.id),
            "sender_name": l.sender_name,
            "query_product_name": l.query_product_name,
            "lead_score": l.lead_score,
            "sender_city": l.sender_city,
            "lead_stage": l.lead_stage,
            "deal_value": l.deal_value,
        }
        for l in hot_leads_result.scalars().all()
    ]

    # Recent activities (last 10)
    activities_result = await db.execute(
        select(Activity, Lead.sender_name)
        .join(Lead, Activity.lead_id == Lead.id)
        .where(Activity.user_id == user.id)
        .order_by(Activity.created_at.desc())
        .limit(10)
    )
    recent_activities = [
        {
            "id": str(row[0].id),
            "activity_type": row[0].activity_type,
            "content": row[0].content,
            "lead_name": row[1] or "Unknown",
            "created_at": row[0].created_at.isoformat() if row[0].created_at else None,
        }
        for row in activities_result.all()
    ]

    # Today's reminders
    reminders_result = await db.execute(
        select(Reminder, Lead.sender_name, Lead.query_product_name)
        .join(Lead, Reminder.lead_id == Lead.id)
        .where(
            Reminder.user_id == user.id,
            Reminder.is_done == False,
            Reminder.remind_at <= now + timedelta(hours=24),
        )
        .order_by(Reminder.remind_at.asc())
        .limit(5)
    )
    today_reminders = [
        {
            "id": str(row[0].id),
            "lead_id": str(row[0].lead_id),
            "lead_name": row[1] or "Unknown",
            "lead_product": row[2] or "N/A",
            "message": row[0].message,
            "remind_at": row[0].remind_at.isoformat(),
        }
        for row in reminders_result.all()
    ]

    # AI recommendations (template-based)
    recommendations = []
    if funnel.get("new", 0) > 0:
        recommendations.append({
            "icon": "📞",
            "title": f"Contact {funnel['new']} new leads",
            "description": "You have uncontacted leads. Respond within 1 hour for best conversion.",
        })
    if hot_leads:
        recommendations.append({
            "icon": "🔥",
            "title": f"Follow up on {len(hot_leads)} hot leads",
            "description": "These leads have high buying intent. Prioritize them today.",
        })
    if today_reminders:
        recommendations.append({
            "icon": "⏰",
            "title": f"Complete {len(today_reminders)} follow-ups",
            "description": "You have pending follow-up reminders for today.",
        })
    if not recommendations:
        recommendations.append({
            "icon": "✨",
            "title": "You're all caught up!",
            "description": "Great job! Consider reviewing your pipeline for optimization.",
        })

    return {
        "funnel": funnel,
        "revenue": {
            "total_pipeline": total_pipeline,
            "won_revenue": won_revenue,
        },
        "hot_leads": hot_leads,
        "recent_activities": recent_activities,
        "today_reminders": today_reminders,
        "recommendations": recommendations,
    }
