"""
AI Service — lead scoring, reply generation, daily digest, and categorization.

Uses OpenAI (gpt-4o-mini) for reply generation with a template-based fallback
when the API is unavailable or quota is exhausted.
"""

from __future__ import annotations

import logging
import os
from collections import Counter
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# ─── OpenAI client (lazy — only created when needed) ────────────────────────

_openai_client: AsyncOpenAI | None = None


def _get_openai_client() -> AsyncOpenAI:
    """Return a module-level singleton ``AsyncOpenAI`` client."""
    global _openai_client
    if _openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. AI reply generation requires a valid key."
            )
        _openai_client = AsyncOpenAI(api_key=api_key)
    return _openai_client


# ─── Reply Generation ────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "You are a professional sales representative for {company}. "
    "Draft a warm, helpful reply to this buyer enquiry. "
    "Include: greeting by name, acknowledge their product interest, "
    "provide product info, mention next steps, professional closing."
)


def _template_reply(
    lead_data: dict[str, Any],
    seller_name: str,
    company_name: str,
    product_info: str,
) -> str:
    """Fallback template-based reply when OpenAI is unavailable."""
    buyer_name = lead_data.get("sender_name") or "Sir/Madam"
    product = lead_data.get("query_product_name") or "your enquiry"

    return (
        f"Dear {buyer_name},\n\n"
        f"Thank you for your interest in {product}. We at {company_name} "
        f"are pleased to receive your enquiry.\n\n"
        f"{product_info}\n\n"
        f"We would love to discuss your requirements in detail. "
        f"Please feel free to call us or reply to this message, and we will "
        f"get back to you at the earliest.\n\n"
        f"Looking forward to hearing from you.\n\n"
        f"Warm regards,\n"
        f"{seller_name}\n"
        f"{company_name}"
    )


async def generate_reply(
    lead_data: dict[str, Any],
    seller_name: str,
    company_name: str,
    product_info: str,
) -> str:
    """Generate a professional reply to a buyer enquiry.

    Uses the OpenAI ``gpt-4o-mini`` model. Falls back to a static template
    if the API call fails for any reason.

    Args:
        lead_data: Dict with lead fields (sender_name, query_product_name,
            query_message, sender_city, etc.).
        seller_name: Name of the seller composing the reply.
        company_name: Seller's company name.
        product_info: Brief product/service description to include.

    Returns:
        The generated reply text.
    """
    try:
        client = _get_openai_client()

        buyer_name = lead_data.get("sender_name") or "the buyer"
        product = lead_data.get("query_product_name") or "your product"
        message = lead_data.get("query_message") or ""
        city = lead_data.get("sender_city") or ""

        user_message = (
            f"Buyer Name: {buyer_name}\n"
            f"Product Interested In: {product}\n"
            f"Buyer Message: {message}\n"
            f"City: {city}\n"
            f"Seller Name: {seller_name}\n"
            f"Company: {company_name}\n"
            f"Product Info: {product_info}\n"
        )

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": _SYSTEM_PROMPT.format(company=company_name),
                },
                {"role": "user", "content": user_message},
            ],
            max_tokens=500,
            temperature=0.7,
        )

        reply = response.choices[0].message.content
        if reply:
            return reply.strip()

        logger.warning("OpenAI returned empty content; falling back to template.")
    except Exception:
        logger.exception("OpenAI reply generation failed; using template fallback.")

    return _template_reply(lead_data, seller_name, company_name, product_info)


# ─── Lead Scoring ────────────────────────────────────────────────────────────

_QUERY_TYPE_SCORES: dict[str, int] = {
    "B": 20,   # Buy lead — highest intent
    "W": 10,   # WhatsApp enquiry
    "BIZ": 15, # Business enquiry
    "P": 5,    # Product enquiry (low intent)
}


def score_lead(lead_data: dict[str, Any]) -> int:
    """Score a lead's quality on a 0–100 scale.

    Scoring rubric:
        - Has phone number:    20 pts
        - Has email:           15 pts
        - Has company name:    15 pts
        - Message length ≥ 50: 10 pts
        - Query type:          5–20 pts (B=20, BIZ=15, W=10, P=5)
        - Has address:         10 pts
        - Has pincode:         10 pts

    Args:
        lead_data: Dict of lead fields.

    Returns:
        Integer score clamped to 0–100.
    """
    score = 0

    if lead_data.get("sender_mobile"):
        score += 20
    if lead_data.get("sender_email"):
        score += 15
    if lead_data.get("sender_company"):
        score += 15

    message = lead_data.get("query_message") or ""
    if len(message) >= 50:
        score += 10

    query_type = (lead_data.get("query_type") or "").upper()
    score += _QUERY_TYPE_SCORES.get(query_type, 0)

    if lead_data.get("sender_address"):
        score += 10
    if lead_data.get("sender_pincode"):
        score += 10

    return min(score, 100)


# ─── Categorization ─────────────────────────────────────────────────────────


def categorize_lead(lead_data: dict[str, Any]) -> str:
    """Categorize a lead as ``hot``, ``warm``, or ``cold`` based on its score.

    Args:
        lead_data: Dict of lead fields (passed to :func:`score_lead`).

    Returns:
        ``"hot"`` (score ≥ 70), ``"warm"`` (40–69), or ``"cold"`` (< 40).
    """
    lead_score = score_lead(lead_data)
    if lead_score >= 70:
        return "hot"
    if lead_score >= 40:
        return "warm"
    return "cold"


# ─── Daily Digest ────────────────────────────────────────────────────────────


def generate_daily_digest(user_id: str, leads_today: list[dict[str, Any]]) -> str:
    """Build a plain-text daily digest email body.

    Includes total leads received, top products enquired about, top cities,
    best-scored leads, and leads requiring attention (cold leads with no reply).

    Args:
        user_id: The tenant user's ID (for personalisation).
        leads_today: List of lead dicts received today.

    Returns:
        Formatted digest string suitable for an email body.
    """
    total = len(leads_today)
    if total == 0:
        return (
            "📊 Daily Lead Digest\n"
            "━━━━━━━━━━━━━━━━━━━\n\n"
            "No new leads received today. Check back tomorrow!\n"
        )

    # Score all leads
    scored_leads = [
        {**lead, "_score": score_lead(lead)} for lead in leads_today
    ]

    # Top products
    products: Counter[str] = Counter()
    for lead in leads_today:
        product = lead.get("query_product_name")
        if product:
            products[product] += 1
    top_products = products.most_common(5)

    # Top cities
    cities: Counter[str] = Counter()
    for lead in leads_today:
        city = lead.get("sender_city")
        if city:
            cities[city] += 1
    top_cities = cities.most_common(5)

    # Best scored leads
    best_leads = sorted(scored_leads, key=lambda x: x["_score"], reverse=True)[:5]

    # Leads requiring attention (cold, no reply sent)
    attention_leads = [
        lead for lead in scored_leads
        if lead["_score"] < 40 and not lead.get("ai_reply_sent")
    ]

    # Build digest
    lines: list[str] = [
        "📊 Daily Lead Digest",
        "━━━━━━━━━━━━━━━━━━━",
        "",
        f"📈 Total Leads Today: {total}",
        "",
    ]

    # Hot / Warm / Cold breakdown
    hot = sum(1 for l in scored_leads if l["_score"] >= 70)
    warm = sum(1 for l in scored_leads if 40 <= l["_score"] < 70)
    cold = total - hot - warm
    lines.append(f"🔥 Hot: {hot}  |  🌤 Warm: {warm}  |  ❄️ Cold: {cold}")
    lines.append("")

    if top_products:
        lines.append("🏷️ Top Products Asked:")
        for product, count in top_products:
            lines.append(f"   • {product} ({count})")
        lines.append("")

    if top_cities:
        lines.append("📍 Top Cities:")
        for city, count in top_cities:
            lines.append(f"   • {city} ({count})")
        lines.append("")

    if best_leads:
        lines.append("⭐ Best Scored Leads:")
        for lead in best_leads:
            name = lead.get("sender_name") or "Unknown"
            product = lead.get("query_product_name") or "N/A"
            score = lead["_score"]
            lines.append(f"   • {name} — {product} (Score: {score})")
        lines.append("")

    if attention_leads:
        lines.append(f"⚠️ Requires Attention ({len(attention_leads)} cold leads, no reply):")
        for lead in attention_leads[:5]:
            name = lead.get("sender_name") or "Unknown"
            product = lead.get("query_product_name") or "N/A"
            lines.append(f"   • {name} — {product}")
        lines.append("")

    lines.append("— IndiaMART Lead Manager")
    return "\n".join(lines)
