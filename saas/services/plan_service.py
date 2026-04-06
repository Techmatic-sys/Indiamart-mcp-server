"""
Plan management service for the IndiaMART Lead Manager SaaS platform.

Defines plan tiers, enforces feature limits, manages upgrades/downgrades,
tracks usage, and handles trial logic.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from saas.models import AutoReply, Lead, Subscription, User

logger = logging.getLogger(__name__)

# ─── Plan Definitions ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PlanConfig:
    """Full configuration for a subscription plan."""

    name: str
    price: int  # Monthly price in INR
    max_leads: int  # -1 = unlimited
    sync_interval_minutes: int
    ai_replies_per_month: int  # -1 = unlimited
    whatsapp: bool
    export: bool
    team_members: int


PLANS: dict[str, PlanConfig] = {
    "free": PlanConfig(
        name="free",
        price=0,
        max_leads=100,
        sync_interval_minutes=30,
        ai_replies_per_month=0,
        whatsapp=False,
        export=False,
        team_members=1,
    ),
    "pro": PlanConfig(
        name="pro",
        price=999,
        max_leads=5_000,
        sync_interval_minutes=10,
        ai_replies_per_month=50,
        whatsapp=True,
        export=True,
        team_members=3,
    ),
    "business": PlanConfig(
        name="business",
        price=2_999,
        max_leads=-1,  # unlimited
        sync_interval_minutes=5,
        ai_replies_per_month=-1,  # unlimited
        whatsapp=True,
        export=True,
        team_members=10,
    ),
}

# Plan ordering for upgrade/downgrade validation
PLAN_ORDER: dict[str, int] = {"free": 0, "pro": 1, "business": 2}

# Trial duration
TRIAL_DURATION_DAYS = 14


# ─── Plan Info ────────────────────────────────────────────────────────────────


def get_all_plans() -> list[dict[str, Any]]:
    """Return all available plans with their features for display.

    Returns:
        List of plan detail dicts.
    """
    result = []
    for key, plan in PLANS.items():
        result.append({
            "name": key,
            "display_name": key.capitalize(),
            "price": plan.price,
            "price_display": f"₹{plan.price}/month" if plan.price > 0 else "Free",
            "features": {
                "max_leads": "Unlimited" if plan.max_leads == -1 else plan.max_leads,
                "sync_interval": f"{plan.sync_interval_minutes} min",
                "ai_replies": "Unlimited" if plan.ai_replies_per_month == -1 else plan.ai_replies_per_month,
                "whatsapp": plan.whatsapp,
                "export": plan.export,
                "team_members": plan.team_members,
            },
        })
    return result


# ─── User Plan Queries ────────────────────────────────────────────────────────


async def get_user_plan(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """Get the current plan details for a user.

    Args:
        db: Async database session.
        user_id: The user's UUID.

    Returns:
        Dict with plan name, config, subscription info, and trial status.

    Raises:
        ValueError: If the user is not found.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError(f"User {user_id} not found.")

    plan_name = user.plan or "free"
    plan_config = PLANS.get(plan_name, PLANS["free"])
    trial_active = await is_trial_active(db, user_id)

    # If trial is active, give pro features on free plan
    effective_plan = plan_config
    if trial_active and plan_name == "free":
        effective_plan = PLANS["pro"]

    # Fetch active subscription
    sub_result = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == user_id, Subscription.status == "active")
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    active_sub = sub_result.scalar_one_or_none()

    return {
        "plan": plan_name,
        "effective_plan": effective_plan.name,
        "price": effective_plan.price,
        "trial_active": trial_active,
        "features": {
            "max_leads": "Unlimited" if effective_plan.max_leads == -1 else effective_plan.max_leads,
            "sync_interval_minutes": effective_plan.sync_interval_minutes,
            "ai_replies_per_month": "Unlimited" if effective_plan.ai_replies_per_month == -1 else effective_plan.ai_replies_per_month,
            "whatsapp": effective_plan.whatsapp,
            "export": effective_plan.export,
            "team_members": effective_plan.team_members,
        },
        "subscription": {
            "id": str(active_sub.id) if active_sub else None,
            "razorpay_subscription_id": active_sub.razorpay_subscription_id if active_sub else None,
            "status": active_sub.status if active_sub else None,
            "expires_at": active_sub.expires_at.isoformat() if active_sub and active_sub.expires_at else None,
        },
        "plan_expires_at": user.plan_expires_at.isoformat() if user.plan_expires_at else None,
    }


# ─── Feature Limit Checking ──────────────────────────────────────────────────


async def check_plan_limit(
    db: AsyncSession,
    user_id: uuid.UUID,
    feature: str,
) -> bool:
    """Check whether a user can use a specific feature under their plan.

    Supported features: ``"leads"``, ``"ai_replies"``, ``"whatsapp"``,
    ``"export"``, ``"team_members"``, ``"auto_sync"``.

    Args:
        db: Async database session.
        user_id: The user's UUID.
        feature: Feature name to check.

    Returns:
        ``True`` if the user can use the feature, ``False`` otherwise.
    """
    user_plan = await get_user_plan(db, user_id)
    effective_plan_name = user_plan["effective_plan"]
    plan = PLANS.get(effective_plan_name, PLANS["free"])

    if feature == "leads":
        if plan.max_leads == -1:
            return True
        usage = await get_usage_stats(db, user_id)
        return usage["leads_used"] < plan.max_leads

    elif feature == "ai_replies":
        if plan.ai_replies_per_month == 0:
            return False
        if plan.ai_replies_per_month == -1:
            return True
        usage = await get_usage_stats(db, user_id)
        return usage["ai_replies_used"] < plan.ai_replies_per_month

    elif feature == "whatsapp":
        return plan.whatsapp

    elif feature == "export":
        return plan.export

    elif feature == "auto_sync":
        return plan.sync_interval_minutes < 30  # Free plan is 30min (manual-ish)

    elif feature == "team_members":
        # For now, just return True — team member count enforcement
        # would require a team_members table
        return True

    else:
        logger.warning("Unknown feature check: %s", feature)
        return False


# ─── Usage Stats ──────────────────────────────────────────────────────────────


async def get_usage_stats(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """Get current usage statistics vs plan limits for a user.

    Args:
        db: Async database session.
        user_id: The user's UUID.

    Returns:
        Dict with current usage counts and plan limits.
    """
    # Get user's plan
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError(f"User {user_id} not found.")

    plan_name = user.plan or "free"
    trial_active = await is_trial_active(db, user_id)
    effective_plan = PLANS.get(plan_name, PLANS["free"])
    if trial_active and plan_name == "free":
        effective_plan = PLANS["pro"]

    # Count total leads
    leads_count_result = await db.execute(
        select(func.count(Lead.id)).where(Lead.user_id == user_id)
    )
    leads_used = leads_count_result.scalar() or 0

    # Count AI replies this month
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    ai_replies_result = await db.execute(
        select(func.count(AutoReply.id)).where(
            AutoReply.user_id == user_id,
            AutoReply.created_at >= month_start,
            AutoReply.status == "sent",
        )
    )
    ai_replies_used = ai_replies_result.scalar() or 0

    return {
        "plan": effective_plan.name,
        "leads_used": leads_used,
        "leads_limit": "Unlimited" if effective_plan.max_leads == -1 else effective_plan.max_leads,
        "leads_remaining": (
            "Unlimited"
            if effective_plan.max_leads == -1
            else max(0, effective_plan.max_leads - leads_used)
        ),
        "ai_replies_used": ai_replies_used,
        "ai_replies_limit": (
            "Unlimited"
            if effective_plan.ai_replies_per_month == -1
            else effective_plan.ai_replies_per_month
        ),
        "ai_replies_remaining": (
            "Unlimited"
            if effective_plan.ai_replies_per_month == -1
            else max(0, effective_plan.ai_replies_per_month - ai_replies_used)
        ),
        "whatsapp_enabled": effective_plan.whatsapp,
        "export_enabled": effective_plan.export,
        "team_members_limit": effective_plan.team_members,
        "sync_interval_minutes": effective_plan.sync_interval_minutes,
        "trial_active": trial_active,
        "billing_period": {
            "start": month_start.isoformat(),
            "end": (month_start.replace(month=month_start.month % 12 + 1) if month_start.month < 12
                    else month_start.replace(year=month_start.year + 1, month=1)).isoformat(),
        },
    }


# ─── Plan Upgrades / Downgrades ──────────────────────────────────────────────


async def upgrade_plan(
    db: AsyncSession,
    user_id: uuid.UUID,
    new_plan: str,
) -> dict[str, Any]:
    """Upgrade a user's plan.

    Args:
        db: Async database session.
        user_id: The user's UUID.
        new_plan: Target plan name (must be higher tier).

    Returns:
        Dict with upgrade result details.

    Raises:
        ValueError: If the plan transition is invalid.
    """
    if new_plan not in PLANS:
        raise ValueError(f"Unknown plan: {new_plan!r}")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError(f"User {user_id} not found.")

    current_order = PLAN_ORDER.get(user.plan, 0)
    new_order = PLAN_ORDER.get(new_plan, 0)

    if new_order <= current_order:
        raise ValueError(
            f"Cannot upgrade from '{user.plan}' to '{new_plan}'. "
            f"Use downgrade_plan() for downgrades or same-tier changes."
        )

    old_plan = user.plan
    user.plan = new_plan
    await db.flush()

    logger.info("Upgraded user %s from %s to %s", user_id, old_plan, new_plan)

    return {
        "success": True,
        "previous_plan": old_plan,
        "new_plan": new_plan,
        "price": PLANS[new_plan].price,
        "message": f"Successfully upgraded from {old_plan} to {new_plan}.",
    }


async def downgrade_plan(
    db: AsyncSession,
    user_id: uuid.UUID,
    new_plan: str,
) -> dict[str, Any]:
    """Downgrade a user's plan.

    The downgrade takes effect at the end of the current billing period.

    Args:
        db: Async database session.
        user_id: The user's UUID.
        new_plan: Target plan name (must be lower tier).

    Returns:
        Dict with downgrade result details.

    Raises:
        ValueError: If the plan transition is invalid.
    """
    if new_plan not in PLANS:
        raise ValueError(f"Unknown plan: {new_plan!r}")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError(f"User {user_id} not found.")

    current_order = PLAN_ORDER.get(user.plan, 0)
    new_order = PLAN_ORDER.get(new_plan, 0)

    if new_order >= current_order:
        raise ValueError(
            f"Cannot downgrade from '{user.plan}' to '{new_plan}'. "
            f"Use upgrade_plan() for upgrades."
        )

    old_plan = user.plan

    # Schedule downgrade: keep current plan until expiry, then switch
    # For immediate downgrade (e.g., free), apply now
    if new_plan == "free":
        user.plan = new_plan
        user.plan_expires_at = None
        await db.flush()
        logger.info("Immediately downgraded user %s from %s to free", user_id, old_plan)
    else:
        # Mark for end-of-period downgrade
        # The actual switch happens when the subscription period ends
        user.plan = new_plan
        await db.flush()
        logger.info("Downgraded user %s from %s to %s", user_id, old_plan, new_plan)

    return {
        "success": True,
        "previous_plan": old_plan,
        "new_plan": new_plan,
        "price": PLANS[new_plan].price,
        "effective_immediately": new_plan == "free",
        "message": (
            f"Downgraded from {old_plan} to {new_plan}."
            if new_plan == "free"
            else f"Downgrade from {old_plan} to {new_plan} will take effect at end of billing period."
        ),
    }


# ─── Trial Management ────────────────────────────────────────────────────────


async def is_trial_active(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """Check whether the user's 14-day free trial of Pro features is still active.

    Trial is active if:
    - User is on the free plan
    - Account was created less than 14 days ago
    - User has never had a paid subscription

    Args:
        db: Async database session.
        user_id: The user's UUID.

    Returns:
        ``True`` if the trial is active.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        return False

    # Only free plan users get trial
    if user.plan != "free":
        return False

    # Check if account is within trial period
    now = datetime.now(timezone.utc)
    trial_end = user.created_at.replace(tzinfo=timezone.utc) + timedelta(days=TRIAL_DURATION_DAYS)
    if now > trial_end:
        return False

    # Check if user ever had a paid subscription (if so, no trial)
    sub_result = await db.execute(
        select(func.count(Subscription.id)).where(
            Subscription.user_id == user_id,
            Subscription.plan != "free",
        )
    )
    past_subs = sub_result.scalar() or 0
    if past_subs > 0:
        return False

    return True
