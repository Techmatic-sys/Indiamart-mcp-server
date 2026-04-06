"""
Morning Briefing, WhatsApp Report, and ROI Calculator API Routes.

Provides endpoints for:
- /api/briefing/today        — JSON daily briefing
- /api/briefing/whatsapp-format — WhatsApp-formatted text briefing
- /api/analytics/roi         — ROI calculation vs IndiaMART subscription cost
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from saas.auth import get_current_active_user
from saas.database import get_db
from saas.models import Activity, Lead, Reminder, User

router = APIRouter(prefix="/api", tags=["Briefing & ROI"])

# IndiaMART subscription cost (can be overridden by env var)
DEFAULT_SUBSCRIPTION_COST = float(os.getenv("INDIAMART_SUBSCRIPTION_COST", "15000"))


# ─── Helper: Build Briefing Data ─────────────────────────────────────────────


async def _build_briefing(user: User, db: AsyncSession) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    three_days_ago = now - timedelta(days=3)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    uid = str(user.id)

    # ── a) New leads in last 24h ──────────────────────────────────────────
    new_leads_result = await db.execute(
        select(func.count()).select_from(Lead).where(
            Lead.user_id == uid,
            Lead.created_at >= yesterday_start,
        )
    )
    new_leads_count: int = new_leads_result.scalar_one() or 0

    # ── b) Hot leads (score >= 70) ────────────────────────────────────────
    hot_result = await db.execute(
        select(Lead).where(
            Lead.user_id == uid,
            Lead.lead_score >= 70,
            Lead.lead_stage.not_in(["won", "lost"]),
        ).order_by(Lead.lead_score.desc()).limit(10)
    )
    hot_leads_rows = hot_result.scalars().all()
    hot_leads = [
        {
            "id": l.id,
            "name": l.sender_name or "Unknown",
            "company": l.sender_company or "",
            "product": l.query_product_name or "",
            "score": l.lead_score or 0,
            "stage": l.lead_stage,
            "deal_value": l.deal_value,
        }
        for l in hot_leads_rows
    ]

    # ── c) Overdue follow-ups (contacted/qualified/proposal with no activity in 3+ days) ──
    active_stages = ["contacted", "qualified", "proposal", "negotiation"]

    active_leads_result = await db.execute(
        select(Lead).where(
            Lead.user_id == uid,
            Lead.lead_stage.in_(active_stages),
        )
    )
    active_leads = active_leads_result.scalars().all()

    # For each active lead, check if last activity was > 3 days ago
    overdue_followups = []
    for lead in active_leads:
        last_act_result = await db.execute(
            select(Activity.created_at).where(
                Activity.lead_id == str(lead.id),
                Activity.user_id == uid,
            ).order_by(Activity.created_at.desc()).limit(1)
        )
        last_act = last_act_result.scalar_one_or_none()
        if last_act is None or last_act < three_days_ago:
            overdue_followups.append({
                "id": lead.id,
                "name": lead.sender_name or "Unknown",
                "company": lead.sender_company or "",
                "product": lead.query_product_name or "",
                "stage": lead.lead_stage,
                "deal_value": lead.deal_value,
                "last_activity": last_act.isoformat() if last_act else None,
            })

    # ── d) Today's reminders ──────────────────────────────────────────────
    today_end = today_start + timedelta(days=1)
    reminders_result = await db.execute(
        select(Reminder).where(
            Reminder.user_id == uid,
            Reminder.remind_at >= today_start,
            Reminder.remind_at < today_end,
            Reminder.is_done == False,
        ).order_by(Reminder.remind_at)
    )
    reminders_rows = reminders_result.scalars().all()
    today_reminders = [
        {
            "id": r.id,
            "message": r.message,
            "remind_at": r.remind_at.isoformat(),
            "lead_id": r.lead_id,
        }
        for r in reminders_rows
    ]

    # ── e) Pipeline summary ───────────────────────────────────────────────
    stages = ["new", "contacted", "qualified", "proposal", "negotiation", "won", "lost"]
    by_stage: dict[str, int] = {}
    total_value = 0.0
    won_this_month = 0.0

    for stage in stages:
        count_result = await db.execute(
            select(func.count()).select_from(Lead).where(
                Lead.user_id == uid, Lead.lead_stage == stage
            )
        )
        by_stage[stage] = count_result.scalar_one() or 0

        val_result = await db.execute(
            select(func.sum(Lead.deal_value)).where(
                Lead.user_id == uid,
                Lead.lead_stage == stage,
                Lead.deal_value.is_not(None),
            )
        )
        stage_val = val_result.scalar_one() or 0.0
        if stage not in ("won", "lost"):
            total_value += stage_val

        if stage == "won":
            won_month_result = await db.execute(
                select(func.sum(Lead.deal_value)).where(
                    Lead.user_id == uid,
                    Lead.lead_stage == "won",
                    Lead.created_at >= month_start,
                    Lead.deal_value.is_not(None),
                )
            )
            won_this_month = won_month_result.scalar_one() or 0.0

    pipeline_summary = {
        "total_value": total_value,
        "won_this_month": won_this_month,
        "by_stage": by_stage,
    }

    # ── f) Yesterday activity count ───────────────────────────────────────
    yesterday_act_result = await db.execute(
        select(func.count()).select_from(Activity).where(
            Activity.user_id == uid,
            Activity.created_at >= yesterday_start,
            Activity.created_at < today_start,
        )
    )
    yesterday_activity: int = yesterday_act_result.scalar_one() or 0

    # ── g) Suggested actions (top 3) ──────────────────────────────────────
    suggested_actions: list[str] = []

    # Hot leads with no contact in 3+ days
    for lead in hot_leads_rows[:3]:
        last_act_result = await db.execute(
            select(Activity.created_at).where(
                Activity.lead_id == str(lead.id),
                Activity.user_id == uid,
            ).order_by(Activity.created_at.desc()).limit(1)
        )
        last_act = last_act_result.scalar_one_or_none()
        if last_act is None or last_act < three_days_ago:
            value_str = f"₹{lead.deal_value/100000:.1f}L" if lead.deal_value else ""
            product_str = lead.query_product_name or "enquiry"
            name_str = lead.sender_name or "Lead"
            action = f"Call {name_str}"
            if value_str:
                action += f" ({value_str} {product_str})"
            action += " — hot lead, no contact in 3+ days"
            suggested_actions.append(action)
            if len(suggested_actions) >= 2:
                break

    # Proposal stage leads
    proposal_result = await db.execute(
        select(Lead).where(
            Lead.user_id == uid,
            Lead.lead_stage == "proposal",
        ).limit(3)
    )
    proposal_leads = proposal_result.scalars().all()
    if proposal_leads:
        lead = proposal_leads[0]
        name_str = lead.sender_name or "Lead"
        suggested_actions.append(f"Send quotation to {name_str} — proposal stage, awaiting response")

    # Contacted leads overdue
    if len(overdue_followups) > 0:
        overdue_count = len(overdue_followups)
        suggested_actions.append(
            f"Follow up with {overdue_count} contacted lead{'s' if overdue_count > 1 else ''} — they've been waiting 3+ days"
        )

    # Trim to top 3
    suggested_actions = suggested_actions[:3]
    if not suggested_actions:
        if new_leads_count > 0:
            suggested_actions.append(f"Review {new_leads_count} new lead{'s' if new_leads_count > 1 else ''} received recently")
        else:
            suggested_actions.append("Keep the momentum going — sync your IndiaMART leads!")

    # ── h) Motivational stat ──────────────────────────────────────────────
    # Simple heuristic: if won_this_month >= 80% of a notional ₹15L target → on track
    monthly_target = float(os.getenv("MONTHLY_TARGET", "1500000"))
    won_lakhs = won_this_month / 100000
    target_lakhs = monthly_target / 100000
    if won_this_month >= monthly_target * 0.8:
        motivational_stat = f"You're on track for ₹{target_lakhs:.0f}L this month! 🚀"
    else:
        gap = max(0, monthly_target - won_this_month)
        gap_lakhs = gap / 100000
        motivational_stat = f"₹{gap_lakhs:.1f}L to go — push 2 more deals to hit your target! 💪"

    return {
        "generated_at": now.isoformat(),
        "new_leads_count": new_leads_count,
        "hot_leads": hot_leads,
        "overdue_followups": overdue_followups,
        "today_reminders": today_reminders,
        "pipeline_summary": pipeline_summary,
        "yesterday_activity": yesterday_activity,
        "suggested_actions": suggested_actions,
        "motivational_stat": motivational_stat,
    }


# ─── Routes ──────────────────────────────────────────────────────────────────


@router.get("/briefing/today")
async def get_briefing_today(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return a JSON morning briefing for the authenticated user."""
    return await _build_briefing(user, db)


@router.get("/briefing/whatsapp-format")
async def get_briefing_whatsapp(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return the morning briefing as a WhatsApp-friendly text message."""
    data = await _build_briefing(user, db)

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%-d %B %Y") if hasattr(now, "strftime") else now.strftime("%d %B %Y")
    # Windows-compatible date format
    try:
        date_str = now.strftime("%-d %B %Y")
    except ValueError:
        date_str = now.strftime("%d %B %Y").lstrip("0")

    ps = data["pipeline_summary"]
    total_lakhs = ps["total_value"] / 100000
    won_lakhs = ps["won_this_month"] / 100000

    hot_count = len(data["hot_leads"])
    overdue_count = len(data["overdue_followups"])
    reminders_count = len(data["today_reminders"])

    actions = data["suggested_actions"]
    action_lines = "\n".join(f"{i+1}. {a}" for i, a in enumerate(actions))

    lines = [
        "🌅 *LeadFlow Morning Briefing*",
        f"📅 {date_str}",
        "",
        f"📥 *New Leads:* {data['new_leads_count']} received in last 24h",
        f"🔥 *Hot Leads:* {hot_count} need attention",
        f"⏰ *Overdue:* {overdue_count} follow-up{'s' if overdue_count != 1 else ''} pending",
        f"🔔 *Reminders Today:* {reminders_count}",
        "",
        f"💰 *Pipeline:* ₹{total_lakhs:.1f}L active",
        f"   Won this month: ₹{won_lakhs:.1f}L",
        "",
        "📋 *Top Actions Today:*",
        action_lines,
        "",
        f"💪 {data['motivational_stat']}",
        "",
        "_Powered by LeadFlow CRM_",
    ]

    text = "\n".join(lines)

    return {
        "text": text,
        "briefing": data,
    }


@router.get("/analytics/roi")
async def get_roi(
    subscription_cost: float = Query(DEFAULT_SUBSCRIPTION_COST, description="Monthly IndiaMART subscription cost in INR"),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Calculate ROI on IndiaMART subscription based on won deals."""
    uid = str(user.id)

    # Total leads
    total_leads_result = await db.execute(
        select(func.count()).select_from(Lead).where(Lead.user_id == uid)
    )
    total_leads: int = total_leads_result.scalar_one() or 0

    # Won deals
    won_result = await db.execute(
        select(func.count(), func.sum(Lead.deal_value)).where(
            Lead.user_id == uid,
            Lead.lead_stage == "won",
            Lead.deal_value.is_not(None),
        )
    )
    row = won_result.one()
    won_deals: int = row[0] or 0
    won_value: float = row[1] or 0.0

    roi_multiple = round(won_value / subscription_cost, 1) if subscription_cost > 0 else 0
    cost_per_lead = round(subscription_cost / total_leads, 0) if total_leads > 0 else 0
    avg_deal_size = round(won_value / won_deals, 0) if won_deals > 0 else 0

    return {
        "won_deals": won_deals,
        "won_value": won_value,
        "subscription_cost": subscription_cost,
        "roi_multiple": roi_multiple,
        "cost_per_lead": cost_per_lead,
        "avg_deal_size": avg_deal_size,
        "total_leads": total_leads,
    }
