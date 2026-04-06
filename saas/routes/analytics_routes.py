"""
Analytics API routes for LeadFlow CRM.

Provides endpoints for:
- Competitor Intelligence Dashboard
- Revenue Analytics
- Conversion Funnel Analysis
- Geographic Lead Heatmap
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from saas.auth import get_current_active_user
from saas.database import get_db
from saas.models import Lead, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])

# ─── Competitor keyword map ──────────────────────────────────────────────────

COMPETITOR_KEYWORDS = {
    "alibaba": "Alibaba",
    "tradeindia": "TradeIndia",
    "justdial": "JustDial",
    "amazon": "Amazon",
    "flipkart": "Flipkart",
    "made-in-china": "Made-in-China",
    "cheaper": "Price Comparison",
    "compare": "Supplier Comparison",
    "alternative": "Alternative Supplier",
    "other supplier": "Other Supplier",
    "better price": "Price Negotiation",
    "quotation from": "Multiple Quotes",
    "exportersindia": "ExportersIndia",
    "sulekha": "Sulekha",
    "snapdeal": "Snapdeal",
    "shopclues": "ShopClues",
    "meesho": "Meesho",
}

# ─── Indian state mapping for cities ────────────────────────────────────────

CITY_STATE_MAP = {
    "mumbai": "Maharashtra", "pune": "Maharashtra", "nagpur": "Maharashtra",
    "nashik": "Maharashtra", "thane": "Maharashtra", "aurangabad": "Maharashtra",
    "delhi": "Delhi", "new delhi": "Delhi", "noida": "Uttar Pradesh",
    "ghaziabad": "Uttar Pradesh", "gurugram": "Haryana", "faridabad": "Haryana",
    "bangalore": "Karnataka", "bengaluru": "Karnataka", "mysuru": "Karnataka",
    "hyderabad": "Telangana", "secunderabad": "Telangana", "warangal": "Telangana",
    "chennai": "Tamil Nadu", "coimbatore": "Tamil Nadu", "madurai": "Tamil Nadu",
    "tiruppur": "Tamil Nadu", "salem": "Tamil Nadu",
    "kolkata": "West Bengal", "howrah": "West Bengal", "durgapur": "West Bengal",
    "ahmedabad": "Gujarat", "surat": "Gujarat", "rajkot": "Gujarat",
    "vadodara": "Gujarat", "gandhinagar": "Gujarat",
    "jaipur": "Rajasthan", "jodhpur": "Rajasthan", "udaipur": "Rajasthan",
    "ludhiana": "Punjab", "amritsar": "Punjab", "jalandhar": "Punjab",
    "chandigarh": "Chandigarh", "lucknow": "Uttar Pradesh", "kanpur": "Uttar Pradesh",
    "agra": "Uttar Pradesh", "meerut": "Uttar Pradesh", "varanasi": "Uttar Pradesh",
    "bhopal": "Madhya Pradesh", "indore": "Madhya Pradesh",
    "kochi": "Kerala", "thiruvananthapuram": "Kerala",
    "bhubaneswar": "Odisha", "patna": "Bihar",
    "visakhapatnam": "Andhra Pradesh", "vijayawada": "Andhra Pradesh",
}


def _scan_competitor_mentions(message: str) -> list[str]:
    """Return list of competitor canonical names mentioned in message."""
    msg_lower = message.lower()
    found = []
    for kw, name in COMPETITOR_KEYWORDS.items():
        if kw in msg_lower and name not in found:
            found.append(name)
    return found


# ─── Competitor Dashboard ────────────────────────────────────────────────────


@router.get("/competitors")
async def get_competitor_dashboard(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Aggregate competitor mentions across all leads."""
    result = await db.execute(
        select(Lead).where(
            Lead.user_id == user.id,
            Lead.query_message.isnot(None),
        )
    )
    leads = result.scalars().all()

    # Aggregate by competitor name
    competitor_data: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"mentions": 0, "leads": [], "won": 0, "total": 0}
    )

    for lead in leads:
        found = _scan_competitor_mentions(lead.query_message or "")
        for comp_name in found:
            competitor_data[comp_name]["mentions"] += 1
            competitor_data[comp_name]["leads"].append(str(lead.id))
            competitor_data[comp_name]["total"] += 1
            if lead.lead_stage == "won":
                competitor_data[comp_name]["won"] += 1

    competitors = []
    for comp_name, data in sorted(
        competitor_data.items(), key=lambda x: x[1]["mentions"], reverse=True
    ):
        total = data["total"]
        won = data["won"]
        win_rate = round((won / total) * 100) if total > 0 else 0
        competitors.append({
            "competitor": comp_name,
            "mentions": data["mentions"],
            "leads": data["leads"],
            "win_rate_vs": win_rate,
        })

    return {
        "competitors": competitors,
        "total_competitor_mentions": sum(c["mentions"] for c in competitors),
        "most_common": competitors[0]["competitor"] if competitors else None,
        "summary": (
            f"Found {len(competitors)} competitor(s) mentioned across {len(leads)} leads."
            if competitors else "No competitor mentions detected in your leads."
        ),
    }


# ─── Revenue Analytics ───────────────────────────────────────────────────────


@router.get("/revenue")
async def get_revenue_analytics(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Monthly revenue data with pipeline and won deals."""
    result = await db.execute(
        select(Lead).where(
            Lead.user_id == user.id,
            Lead.deal_value.isnot(None),
        )
    )
    leads = result.scalars().all()

    # Group by month
    monthly: dict[str, dict[str, float]] = defaultdict(lambda: {"closed": 0.0, "pipeline": 0.0})
    for lead in leads:
        created = lead.created_at
        if created:
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            month_key = created.strftime("%Y-%m")
            if lead.lead_stage == "won":
                monthly[month_key]["closed"] += lead.deal_value or 0
            else:
                monthly[month_key]["pipeline"] += lead.deal_value or 0

    # Sort months
    sorted_months = sorted(monthly.keys())
    monthly_list = [
        {
            "month": m,
            "closed": round(monthly[m]["closed"], 2),
            "pipeline": round(monthly[m]["pipeline"], 2),
        }
        for m in sorted_months
    ]

    # Current month target (heuristic: 20% more than best month)
    best_closed = max((m["closed"] for m in monthly_list), default=0)
    current_month_target = round(best_closed * 1.2) if best_closed > 0 else 800000

    # ROI estimates (heuristic defaults)
    total_won = sum(m["closed"] for m in monthly_list)
    indiamart_spend = max(15000, round(total_won * 0.03))  # ~3% of revenue as spend estimate
    roi_multiple = round(total_won / indiamart_spend, 1) if indiamart_spend > 0 else 0

    return {
        "monthly": monthly_list,
        "targets": {
            "current_month": current_month_target,
        },
        "roi": {
            "indiamart_spend": indiamart_spend,
            "deals_closed": round(total_won, 2),
            "roi_multiple": roi_multiple,
        },
        "summary": {
            "total_won": round(total_won, 2),
            "total_pipeline": round(sum(m["pipeline"] for m in monthly_list), 2),
            "months_tracked": len(monthly_list),
        },
    }


# ─── Conversion Funnel ───────────────────────────────────────────────────────


@router.get("/funnel")
async def get_conversion_funnel(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Detailed conversion rates between each pipeline stage."""
    STAGES = ["new", "contacted", "qualified", "proposal", "negotiation", "won", "lost"]

    # Count per stage
    stage_counts: dict[str, int] = {}
    for stage in STAGES:
        count = (await db.execute(
            select(func.count()).select_from(Lead).where(
                Lead.user_id == user.id,
                Lead.lead_stage == stage,
            )
        )).scalar() or 0
        stage_counts[stage] = count

    total_leads = sum(stage_counts.values())

    # Build transition rates — each stage's count as % of the previous
    ACTIVE_STAGES = ["new", "contacted", "qualified", "proposal", "negotiation", "won"]
    stages_info = []
    prev_count = None
    for i, stage in enumerate(ACTIVE_STAGES[:-1]):
        next_stage = ACTIVE_STAGES[i + 1]
        from_count = stage_counts.get(stage, 0)
        to_count = stage_counts.get(next_stage, 0)

        # Rate: how many made it to next stage (relative to current stage occupancy)
        total_at_from = from_count + to_count + stage_counts.get("won", 0) if i == 0 else from_count + to_count
        rate = round((to_count / total_at_from) * 100, 1) if total_at_from > 0 else 0

        # Avg days heuristic (mocked — would need timestamps in activities)
        avg_days_map = {
            ("new", "contacted"): 1.5,
            ("contacted", "qualified"): 3.0,
            ("qualified", "proposal"): 4.5,
            ("proposal", "negotiation"): 7.0,
            ("negotiation", "won"): 5.0,
        }
        avg_days = avg_days_map.get((stage, next_stage), 3.0)

        stages_info.append({
            "from": stage,
            "to": next_stage,
            "from_count": from_count,
            "to_count": to_count,
            "rate": rate,
            "avg_days": avg_days,
        })

    # Find bottleneck (lowest conversion rate)
    bottleneck_stage = None
    bottleneck_rate = 101.0
    for s in stages_info:
        if s["rate"] < bottleneck_rate:
            bottleneck_rate = s["rate"]
            bottleneck_stage = f"{s['from']}_to_{s['to']}"

    # Bottleneck suggestion
    SUGGESTIONS = {
        "new_to_contacted": "You're not contacting new leads fast enough. Set up auto-reply or WhatsApp templates.",
        "contacted_to_qualified": "Many leads aren't being qualified. Ask better discovery questions early.",
        "qualified_to_proposal": "You're not converting qualified leads to proposals. Speed up your quoting process.",
        "proposal_to_negotiation": "Proposals aren't getting traction. Try including case studies and ROI calculators.",
        "negotiation_to_won": "Deals are stalling in negotiation. Consider offering a time-limited discount or payment flexibility.",
    }
    suggestion = SUGGESTIONS.get(bottleneck_stage or "", "Focus on the lowest conversion stage to improve overall pipeline health.")

    return {
        "stages": stages_info,
        "stage_counts": stage_counts,
        "total_leads": total_leads,
        "bottleneck": bottleneck_stage,
        "bottleneck_rate": bottleneck_rate if bottleneck_stage else None,
        "suggestion": suggestion,
        "overall_win_rate": round(
            (stage_counts.get("won", 0) / total_leads) * 100, 1
        ) if total_leads > 0 else 0,
    }


# ─── Geography Heatmap ───────────────────────────────────────────────────────


@router.get("/geography")
async def get_geography_heatmap(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Leads by city with counts and deal values."""
    result = await db.execute(
        select(Lead).where(Lead.user_id == user.id)
    )
    leads = result.scalars().all()

    city_data: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "deal_value": 0.0, "state": "Unknown"}
    )

    for lead in leads:
        city_raw = (lead.sender_city or "").strip()
        if not city_raw:
            city_raw = "Unknown"
        city_key = city_raw  # Preserve original casing for display
        city_lower = city_raw.lower()

        city_data[city_key]["count"] += 1
        city_data[city_key]["deal_value"] += lead.deal_value or 0
        if city_data[city_key]["state"] == "Unknown":
            city_data[city_key]["state"] = CITY_STATE_MAP.get(city_lower, "Unknown")

    # Sort by count desc
    cities_list = sorted(
        [
            {
                "city": city,
                "state": data["state"],
                "count": data["count"],
                "deal_value": round(data["deal_value"], 2),
            }
            for city, data in city_data.items()
        ],
        key=lambda x: x["count"],
        reverse=True,
    )

    top_city = cities_list[0]["city"] if cities_list else None
    total_leads = sum(c["count"] for c in cities_list)

    # Expansion suggestion
    expansion_suggestion = ""
    if top_city and total_leads > 0:
        top_pct = round((cities_list[0]["count"] / total_leads) * 100)
        expansion_suggestion = (
            f"You get {top_pct}% of leads from {top_city}. "
            "Consider running targeted campaigns in nearby cities to diversify your pipeline."
        )

    return {
        "cities": cities_list,
        "top_city": top_city,
        "total_leads": total_leads,
        "cities_count": len(cities_list),
        "expansion_suggestion": expansion_suggestion,
    }
