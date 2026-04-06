"""
Payment and billing API routes for the IndiaMART Lead Manager SaaS platform.

Provides endpoints for plan listing, subscription management, Razorpay
webhook handling, invoice retrieval, and usage tracking.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from saas.auth import get_current_active_user
from saas.database import get_db
from saas.models import Subscription, User
from saas.services.payment_service import (
    cancel_subscription as razorpay_cancel_subscription,
    create_subscription as razorpay_create_subscription,
    generate_invoice,
    verify_payment,
    verify_webhook_signature,
)
from saas.services.plan_service import (
    PLANS,
    get_all_plans,
    get_usage_stats,
    get_user_plan,
    upgrade_plan,
    downgrade_plan,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["billing"])


# ─── Request / Response Schemas ───────────────────────────────────────────────


class SubscribeRequest(BaseModel):
    """Request body for creating a new subscription."""
    plan: str = Field(..., pattern=r"^(pro|business)$", description="Target plan name")


class CancelRequest(BaseModel):
    """Request body for cancellation (optional reason)."""
    reason: str | None = None


class WebhookEvent(BaseModel):
    """Minimal representation of a Razorpay webhook event."""
    event: str
    payload: dict[str, Any] = {}


# ─── GET /api/plans ───────────────────────────────────────────────────────────


@router.get("/plans")
async def list_plans() -> dict[str, Any]:
    """List all available subscription plans with features and pricing.

    Returns:
        JSON with a list of plans and their feature breakdowns.
    """
    return {
        "plans": get_all_plans(),
    }


# ─── GET /api/billing ────────────────────────────────────────────────────────


@router.get("/billing")
async def get_billing_info(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get the current user's billing info: plan, usage, next billing date.

    Returns:
        JSON with plan details, usage stats, and subscription metadata.
    """
    plan_info = await get_user_plan(db, current_user.id)
    usage = await get_usage_stats(db, current_user.id)

    # Get active subscription for next billing date
    sub_result = await db.execute(
        select(Subscription)
        .where(
            Subscription.user_id == current_user.id,
            Subscription.status == "active",
        )
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    active_sub = sub_result.scalar_one_or_none()

    return {
        "plan": plan_info,
        "usage": usage,
        "billing": {
            "next_billing_date": (
                active_sub.expires_at.isoformat() if active_sub else None
            ),
            "amount": PLANS.get(current_user.plan, PLANS["free"]).price,
            "currency": "INR",
            "subscription_id": (
                active_sub.razorpay_subscription_id if active_sub else None
            ),
        },
    }


# ─── POST /api/billing/subscribe ─────────────────────────────────────────────


@router.post("/billing/subscribe", status_code=status.HTTP_201_CREATED)
async def create_subscription(
    body: SubscribeRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a new Razorpay subscription for the current user.

    Args:
        body: Must include ``plan`` (``"pro"`` or ``"business"``).

    Returns:
        JSON with Razorpay subscription ID and payment link.
    """
    target_plan = body.plan

    # Check if user already has an active subscription
    existing_sub = await db.execute(
        select(Subscription)
        .where(
            Subscription.user_id == current_user.id,
            Subscription.status == "active",
        )
        .limit(1)
    )
    if existing_sub.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You already have an active subscription. Cancel it first or use the upgrade endpoint.",
        )

    try:
        razorpay_sub = await razorpay_create_subscription(
            user_id=current_user.id,
            plan=target_plan,
            customer_email=current_user.email,
            customer_name=current_user.name,
            customer_phone=current_user.phone,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )

    # Create a pending subscription record
    now = datetime.now(timezone.utc)
    subscription = Subscription(
        user_id=current_user.id,
        plan=target_plan,
        razorpay_subscription_id=razorpay_sub["subscription_id"],
        amount=PLANS[target_plan].price,
        currency="INR",
        status="active",
        starts_at=now,
        expires_at=now + timedelta(days=30),
    )
    db.add(subscription)
    await db.flush()

    logger.info(
        "Created subscription %s for user %s (plan=%s)",
        razorpay_sub["subscription_id"],
        current_user.id,
        target_plan,
    )

    return {
        "message": f"Subscription created for {target_plan} plan.",
        "subscription_id": razorpay_sub["subscription_id"],
        "payment_link": razorpay_sub["short_url"],
        "status": razorpay_sub["status"],
    }


# ─── POST /api/billing/cancel ────────────────────────────────────────────────


@router.post("/billing/cancel")
async def cancel_subscription(
    body: CancelRequest | None = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Cancel the current user's active subscription.

    Returns:
        JSON with cancellation confirmation.
    """
    sub_result = await db.execute(
        select(Subscription)
        .where(
            Subscription.user_id == current_user.id,
            Subscription.status == "active",
        )
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    active_sub = sub_result.scalar_one_or_none()

    if active_sub is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active subscription found.",
        )

    # Cancel on Razorpay
    if active_sub.razorpay_subscription_id:
        cancelled = await razorpay_cancel_subscription(
            active_sub.razorpay_subscription_id
        )
        if not cancelled:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to cancel subscription with Razorpay. Please try again.",
            )

    # Update local record
    active_sub.status = "cancelled"
    await db.flush()

    # Downgrade user to free
    await downgrade_plan(db, current_user.id, "free")

    logger.info("Cancelled subscription for user %s", current_user.id)

    return {
        "message": "Subscription cancelled successfully.",
        "effective_plan": "free",
    }


# ─── POST /api/billing/webhook ───────────────────────────────────────────────


@router.post("/billing/webhook")
async def razorpay_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Razorpay webhook receiver.

    Handles the following events:
    - ``payment.captured`` — Payment was successfully captured.
    - ``subscription.charged`` — Recurring subscription charge succeeded.
    - ``subscription.cancelled`` — Subscription was cancelled.
    - ``subscription.halted`` — Subscription payments failed repeatedly.
    - ``subscription.completed`` — Subscription completed all cycles.

    The endpoint verifies the webhook signature before processing.

    Returns:
        ``{"status": "ok"}`` on success.
    """
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    # Verify webhook signature
    is_valid = await verify_webhook_signature(body, signature)
    if not is_valid:
        logger.warning("Invalid webhook signature received")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook signature.",
        )

    import json
    try:
        event_data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload.",
        )

    event_type = event_data.get("event", "")
    payload = event_data.get("payload", {})

    logger.info("Received webhook event: %s", event_type)

    if event_type == "payment.captured":
        await _handle_payment_captured(db, payload)
    elif event_type == "subscription.charged":
        await _handle_subscription_charged(db, payload)
    elif event_type in ("subscription.cancelled", "subscription.halted"):
        await _handle_subscription_cancelled(db, payload)
    elif event_type == "subscription.completed":
        await _handle_subscription_completed(db, payload)
    else:
        logger.info("Unhandled webhook event: %s", event_type)

    return {"status": "ok"}


async def _handle_payment_captured(db: AsyncSession, payload: dict[str, Any]) -> None:
    """Process a payment.captured webhook event."""
    payment_entity = payload.get("payment", {}).get("entity", {})
    notes = payment_entity.get("notes", {})
    user_id = notes.get("user_id")

    if not user_id:
        logger.warning("payment.captured: no user_id in notes")
        return

    logger.info("Payment captured for user %s: %s", user_id, payment_entity.get("id"))


async def _handle_subscription_charged(db: AsyncSession, payload: dict[str, Any]) -> None:
    """Process a subscription.charged webhook event (recurring payment success)."""
    sub_entity = payload.get("subscription", {}).get("entity", {})
    razorpay_sub_id = sub_entity.get("id")

    if not razorpay_sub_id:
        logger.warning("subscription.charged: missing subscription ID")
        return

    # Find local subscription
    result = await db.execute(
        select(Subscription).where(
            Subscription.razorpay_subscription_id == razorpay_sub_id
        )
    )
    subscription = result.scalar_one_or_none()

    if subscription is None:
        logger.warning("subscription.charged: no local record for %s", razorpay_sub_id)
        return

    # Extend subscription period
    now = datetime.now(timezone.utc)
    subscription.expires_at = now + timedelta(days=30)
    subscription.status = "active"

    # Update payment ID if present
    payment_entity = payload.get("payment", {}).get("entity", {})
    if payment_entity.get("id"):
        subscription.razorpay_payment_id = payment_entity["id"]

    # Ensure user plan is updated
    user_result = await db.execute(
        select(User).where(User.id == subscription.user_id)
    )
    user = user_result.scalar_one_or_none()
    if user:
        user.plan = subscription.plan
        user.plan_expires_at = subscription.expires_at

    await db.flush()
    logger.info("Subscription %s charged successfully, extended to %s", razorpay_sub_id, subscription.expires_at)


async def _handle_subscription_cancelled(db: AsyncSession, payload: dict[str, Any]) -> None:
    """Process a subscription.cancelled or subscription.halted event."""
    sub_entity = payload.get("subscription", {}).get("entity", {})
    razorpay_sub_id = sub_entity.get("id")

    if not razorpay_sub_id:
        return

    result = await db.execute(
        select(Subscription).where(
            Subscription.razorpay_subscription_id == razorpay_sub_id
        )
    )
    subscription = result.scalar_one_or_none()

    if subscription:
        subscription.status = "cancelled"

        # Downgrade user to free
        user_result = await db.execute(
            select(User).where(User.id == subscription.user_id)
        )
        user = user_result.scalar_one_or_none()
        if user:
            user.plan = "free"
            user.plan_expires_at = None

        await db.flush()
        logger.info("Subscription %s cancelled via webhook", razorpay_sub_id)


async def _handle_subscription_completed(db: AsyncSession, payload: dict[str, Any]) -> None:
    """Process a subscription.completed event (all cycles done)."""
    sub_entity = payload.get("subscription", {}).get("entity", {})
    razorpay_sub_id = sub_entity.get("id")

    if not razorpay_sub_id:
        return

    result = await db.execute(
        select(Subscription).where(
            Subscription.razorpay_subscription_id == razorpay_sub_id
        )
    )
    subscription = result.scalar_one_or_none()

    if subscription:
        subscription.status = "expired"
        await db.flush()
        logger.info("Subscription %s completed all cycles", razorpay_sub_id)


# ─── GET /api/billing/invoices ────────────────────────────────────────────────


@router.get("/billing/invoices")
async def list_invoices(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List all invoices for the current user.

    Generates invoice data from subscription records.

    Returns:
        JSON with a list of invoice summaries.
    """
    result = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == current_user.id)
        .order_by(Subscription.created_at.desc())
    )
    subscriptions = result.scalars().all()

    invoices = []
    for sub in subscriptions:
        if sub.plan == "free":
            continue

        invoice = await generate_invoice(
            subscription={
                "plan": sub.plan,
                "amount": sub.amount,
                "razorpay_subscription_id": sub.razorpay_subscription_id,
                "razorpay_payment_id": sub.razorpay_payment_id,
                "starts_at": sub.starts_at,
                "expires_at": sub.expires_at,
            },
            user={
                "name": current_user.name,
                "email": current_user.email,
                "company_name": current_user.company_name,
            },
        )
        invoice["id"] = str(sub.id)
        invoice["subscription_status"] = sub.status
        invoices.append(invoice)

    return {
        "invoices": invoices,
        "total": len(invoices),
    }


# ─── GET /api/billing/invoices/{id} ──────────────────────────────────────────


@router.get("/billing/invoices/{invoice_id}")
async def get_invoice(
    invoice_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get a specific invoice by subscription ID.

    Args:
        invoice_id: The subscription UUID (used as invoice reference).

    Returns:
        Full GST-compliant invoice data.
    """
    result = await db.execute(
        select(Subscription).where(
            Subscription.id == invoice_id,
            Subscription.user_id == current_user.id,
        )
    )
    subscription = result.scalar_one_or_none()

    if subscription is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found.",
        )

    invoice = await generate_invoice(
        subscription={
            "plan": subscription.plan,
            "amount": subscription.amount,
            "razorpay_subscription_id": subscription.razorpay_subscription_id,
            "razorpay_payment_id": subscription.razorpay_payment_id,
            "starts_at": subscription.starts_at,
            "expires_at": subscription.expires_at,
        },
        user={
            "name": current_user.name,
            "email": current_user.email,
            "company_name": current_user.company_name,
        },
    )
    invoice["id"] = str(subscription.id)
    invoice["subscription_status"] = subscription.status

    return invoice


# ─── GET /api/billing/usage ──────────────────────────────────────────────────


@router.get("/billing/usage")
async def get_usage(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get current usage vs plan limits for the authenticated user.

    Returns:
        JSON with detailed usage statistics and plan limits.
    """
    usage = await get_usage_stats(db, current_user.id)
    return {
        "user_id": str(current_user.id),
        "plan": current_user.plan,
        "usage": usage,
    }
