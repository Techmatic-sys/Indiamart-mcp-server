"""
AI Auto-Reply Composer API Routes.

Provides endpoints to:
- Compose 3 tailored reply options for a lead (formal, friendly, urgent)
- Send/log a reply as an Activity and mark lead as contacted
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from saas.auth import get_current_active_user
from saas.database import get_db
from saas.models import Activity, Lead, User

router = APIRouter(prefix="/api", tags=["AI Reply Composer"])


# ─── Schemas ─────────────────────────────────────────────────────────────────


class SendReplyRequest(BaseModel):
    reply_text: str = Field(..., min_length=1, max_length=10000)
    send_via: str = Field(..., pattern=r"^(email|whatsapp)$")


class ReplyOption(BaseModel):
    type: str
    subject: str
    body: str


class ComposeReplyResponse(BaseModel):
    lead_id: str
    replies: list[ReplyOption]


class SendReplyResponse(BaseModel):
    success: bool
    activity_id: str


# ─── Keyword Detection Helper ────────────────────────────────────────────────


def _detect_keywords(message: str) -> dict[str, bool]:
    """Detect intent keywords in the query message."""
    msg = (message or "").lower()
    return {
        "urgent": any(w in msg for w in ["urgent", "urgently", "asap", "immediately", "today", "fast"]),
        "price": any(w in msg for w in ["price", "cost", "rate", "pricing", "quote", "quotation", "how much", "charges"]),
        "bulk": any(w in msg for w in ["bulk", "wholesale", "large quantity", "large order", "100", "500", "1000", "lots", "mass"]),
        "sample": any(w in msg for w in ["sample", "trial", "demo", "test piece", "prototype"]),
        "catalogue": any(w in msg for w in ["catalogue", "catalog", "brochure", "product list", "catalog pdf"]),
    }


def _delivery_days(urgent: bool) -> str:
    return "3-5 business days" if urgent else "7-10 business days"


def _compose_formal(
    name: str,
    product: str,
    company: str,
    kw: dict[str, bool],
    seller_phone: str,
) -> ReplyOption:
    extras = []
    if kw["urgent"]:
        extras.append("We understand your requirement is time-sensitive and we are prioritizing your order for the fastest possible dispatch.")
    if kw["price"]:
        extras.append("Our pricing is highly competitive and we offer the best value in the market. We will share a detailed quotation shortly.")
    if kw["bulk"]:
        extras.append("For bulk and wholesale orders, we offer attractive volume discounts. Please share the quantity required so we can provide the best pricing.")
    if kw["sample"]:
        extras.append("We would be happy to arrange a sample for your evaluation before you proceed with the full order.")
    if kw["catalogue"]:
        extras.append("We are sharing our product catalogue with complete specifications for your reference.")

    extra_para = ("\n\n" + " ".join(extras)) if extras else ""

    subject = f"Re: Enquiry for {product} — {company or 'Your Company'}"
    body = (
        f"Dear {name},\n\n"
        f"Thank you for your enquiry regarding {product}. We are pleased to inform you that we can "
        f"fulfill your requirement with the highest quality standards."
        f"{extra_para}\n\n"
        f"We would like to understand your requirements in detail to provide you the best solution. "
        f"Please find our contact details below:\n\n"
        f"📞 Phone: {seller_phone}\n"
        f"🚚 Delivery: {_delivery_days(kw['urgent'])}\n\n"
        f"We look forward to a long and mutually beneficial business relationship.\n\n"
        f"Warm regards,\n[Your Name]\n[Company Name]\n[Phone] | [Email]"
    )
    return ReplyOption(type="formal", subject=subject, body=body)


def _compose_friendly(
    name: str,
    product: str,
    company: str,
    kw: dict[str, bool],
    seller_phone: str,
) -> ReplyOption:
    extras = []
    if kw["urgent"]:
        extras.append("⚡ Since you need it urgently, we can fast-track this — let's connect ASAP!")
    if kw["price"]:
        extras.append("💰 On pricing — we're super competitive, and I'll send you the best rate personally.")
    if kw["bulk"]:
        extras.append("📦 For bulk orders, we have special wholesale pricing — the more you order, the better the deal!")
    if kw["sample"]:
        extras.append("🎁 Happy to send a sample first so you can check the quality before committing!")
    if kw["catalogue"]:
        extras.append("📋 I'll drop our full catalogue with specs and pricing right away!")

    extra_text = ("\n\n" + "\n".join(extras)) if extras else ""

    first_name = name.split()[0] if name else name
    subject = f"Hey {first_name}! About your {product} enquiry 👋"
    body = (
        f"Hi {first_name}! 👋\n\n"
        f"Thanks for reaching out about {product}! Yes, we have this available and ready to ship! "
        f"Here's what I can offer you:"
        f"{extra_text}\n\n"
        f"✅ Product: {product}\n"
        f"✅ Quality: Best in market\n"
        f"🚚 Delivery: {_delivery_days(kw['urgent'])}\n"
        f"📞 Let's talk: {seller_phone}\n\n"
        f"Just give me a call or reply here — I'll get you sorted quickly! 😊\n\n"
        f"Cheers,\n[Your Name]"
    )
    return ReplyOption(type="friendly", subject=subject, body=body)


def _compose_urgent(
    name: str,
    product: str,
    company: str,
    kw: dict[str, bool],
    seller_phone: str,
) -> ReplyOption:
    extras = []
    if kw["price"]:
        extras.append("Best price guaranteed 💯")
    if kw["bulk"]:
        extras.append("Bulk discount available 📦")
    if kw["sample"]:
        extras.append("Sample available on request 🎁")
    if kw["catalogue"]:
        extras.append("Catalogue ready to share 📋")

    flags = " | ".join(extras) if extras else "Ready to fulfill"

    subject = f"Quick Response: {product} — Available & Ready"
    body = (
        f"{name},\n\n"
        f"Got your enquiry for {product}. Quick response:\n\n"
        f"✅ Available: YES\n"
        f"🚚 Can deliver in: {_delivery_days(kw['urgent'])}\n"
        f"💰 Price: Best guaranteed\n"
        f"📦 {flags}\n\n"
        f"📞 Call me NOW: {seller_phone}\n"
        f"(Available 9 AM – 7 PM, Mon–Sat)\n\n"
        f"Don't wait — limited stock available!\n\n"
        f"[Your Name] | [Company]"
    )
    return ReplyOption(type="urgent", subject=subject, body=body)


# ─── Routes ──────────────────────────────────────────────────────────────────


@router.post("/leads/{lead_id}/compose-reply", response_model=ComposeReplyResponse)
async def compose_reply(
    lead_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ComposeReplyResponse:
    """Generate 3 AI reply options (formal, friendly, urgent) for a lead."""
    result = await db.execute(
        select(Lead).where(Lead.id == str(lead_id), Lead.user_id == str(user.id))
    )
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

    name = lead.sender_name or "Sir/Madam"
    product = lead.query_product_name or "your required product"
    company = lead.sender_company or ""
    message = lead.query_message or ""
    seller_phone = user.phone or "[Your Phone]"

    kw = _detect_keywords(message)

    replies = [
        _compose_formal(name, product, company, kw, seller_phone),
        _compose_friendly(name, product, company, kw, seller_phone),
        _compose_urgent(name, product, company, kw, seller_phone),
    ]

    return ComposeReplyResponse(lead_id=str(lead_id), replies=replies)


@router.post("/leads/{lead_id}/send-reply", response_model=SendReplyResponse)
async def send_reply(
    lead_id: str,
    body: SendReplyRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> SendReplyResponse:
    """Log a reply as an Activity and mark lead as contacted if it was new."""
    result = await db.execute(
        select(Lead).where(Lead.id == str(lead_id), Lead.user_id == str(user.id))
    )
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

    # Log as activity
    activity_id = str(uuid.uuid4())
    activity = Activity(
        id=activity_id,
        lead_id=str(lead_id),
        user_id=str(user.id),
        activity_type=body.send_via,  # "email" or "whatsapp"
        content=body.reply_text,
    )
    db.add(activity)

    # Mark as contacted if new
    if lead.lead_stage == "new":
        lead.lead_stage = "contacted"

    await db.commit()

    return SendReplyResponse(success=True, activity_id=activity_id)
