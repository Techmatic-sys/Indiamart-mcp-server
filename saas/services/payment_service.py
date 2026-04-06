"""
Razorpay payment integration for the IndiaMART Lead Manager SaaS platform.

Handles subscription creation, payment verification, cancellation,
one-time payments, and GST-compliant invoice generation.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import razorpay

from saas.config import settings

logger = logging.getLogger(__name__)

# ─── Razorpay Client ─────────────────────────────────────────────────────────

_client: razorpay.Client | None = None


def _get_client() -> razorpay.Client:
    """Lazily initialise and return the Razorpay client singleton."""
    global _client
    if _client is None:
        if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
            raise RuntimeError(
                "RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be set in environment."
            )
        _client = razorpay.Client(
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
        )
    return _client


# ─── Plan → Razorpay Plan ID Mapping ─────────────────────────────────────────

# These should be created once in Razorpay Dashboard or via API and stored.
# Set via environment variables: RAZORPAY_PLAN_ID_PRO, RAZORPAY_PLAN_ID_BUSINESS
import os

RAZORPAY_PLAN_IDS: dict[str, str] = {
    "pro": os.getenv("RAZORPAY_PLAN_ID_PRO", ""),
    "business": os.getenv("RAZORPAY_PLAN_ID_BUSINESS", ""),
}

# Plan prices in paise (Razorpay uses smallest currency unit)
PLAN_PRICES_PAISE: dict[str, int] = {
    "free": 0,
    "pro": 999_00,       # ₹999
    "business": 2999_00,  # ₹2999
}

# GST constants
GST_RATE = 0.18
HSN_CODE = "998314"  # SAC code for SaaS / IT services


# ─── Subscription Management ─────────────────────────────────────────────────


async def create_subscription(
    user_id: uuid.UUID,
    plan: str,
    *,
    customer_email: str | None = None,
    customer_name: str | None = None,
    customer_phone: str | None = None,
) -> dict[str, Any]:
    """Create a Razorpay subscription for the given user and plan.

    Args:
        user_id: Internal user UUID.
        plan: One of ``"free"``, ``"pro"``, or ``"business"``.
        customer_email: Optional email for Razorpay customer record.
        customer_name: Optional name for Razorpay customer record.
        customer_phone: Optional phone for Razorpay customer record.

    Returns:
        Dict with ``subscription_id``, ``short_url``, and ``payment_link``.

    Raises:
        ValueError: If plan is ``"free"`` or unrecognised.
        RuntimeError: If the Razorpay plan ID is not configured.
    """
    if plan == "free":
        raise ValueError("Free plan does not require a Razorpay subscription.")
    if plan not in RAZORPAY_PLAN_IDS:
        raise ValueError(f"Unknown plan: {plan!r}. Expected 'pro' or 'business'.")

    razorpay_plan_id = RAZORPAY_PLAN_IDS[plan]
    if not razorpay_plan_id:
        raise RuntimeError(
            f"Razorpay plan ID for '{plan}' is not configured. "
            f"Set RAZORPAY_PLAN_ID_{plan.upper()} environment variable."
        )

    client = _get_client()

    subscription_data: dict[str, Any] = {
        "plan_id": razorpay_plan_id,
        "total_count": 12,  # 12 billing cycles (1 year)
        "quantity": 1,
        "notes": {
            "user_id": str(user_id),
            "plan": plan,
        },
    }

    # Optionally attach customer info
    if customer_email:
        subscription_data["customer_notify"] = 1
        subscription_data["notes"]["customer_email"] = customer_email

    try:
        subscription = client.subscription.create(subscription_data)
    except Exception as exc:
        logger.error("Razorpay subscription creation failed for user %s: %s", user_id, exc)
        raise

    logger.info(
        "Created Razorpay subscription %s for user %s (plan=%s)",
        subscription.get("id"),
        user_id,
        plan,
    )

    return {
        "subscription_id": subscription["id"],
        "short_url": subscription.get("short_url", ""),
        "payment_link": subscription.get("short_url", ""),
        "status": subscription.get("status", "created"),
    }


async def verify_payment(
    razorpay_payment_id: str,
    razorpay_subscription_id: str,
    razorpay_signature: str,
) -> bool:
    """Verify a Razorpay payment signature using HMAC SHA256.

    The expected signature is computed as::

        HMAC-SHA256(razorpay_payment_id + "|" + razorpay_subscription_id, key_secret)

    Args:
        razorpay_payment_id: Payment ID from Razorpay callback.
        razorpay_subscription_id: Subscription ID from Razorpay callback.
        razorpay_signature: Signature from Razorpay callback.

    Returns:
        ``True`` if the signature is valid, ``False`` otherwise.
    """
    try:
        message = f"{razorpay_payment_id}|{razorpay_subscription_id}"
        expected_signature = hmac.new(
            settings.RAZORPAY_KEY_SECRET.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected_signature, razorpay_signature)
    except Exception as exc:
        logger.error("Payment verification failed: %s", exc)
        return False


async def cancel_subscription(subscription_id: str) -> bool:
    """Cancel a Razorpay subscription.

    Args:
        subscription_id: The Razorpay subscription ID to cancel.

    Returns:
        ``True`` if cancellation succeeded, ``False`` otherwise.
    """
    try:
        client = _get_client()
        client.subscription.cancel(subscription_id)
        logger.info("Cancelled Razorpay subscription %s", subscription_id)
        return True
    except Exception as exc:
        logger.error("Failed to cancel subscription %s: %s", subscription_id, exc)
        return False


async def get_subscription_status(subscription_id: str) -> dict[str, Any]:
    """Fetch the current status of a Razorpay subscription.

    Args:
        subscription_id: The Razorpay subscription ID.

    Returns:
        Dict with subscription details from Razorpay.
    """
    try:
        client = _get_client()
        subscription = client.subscription.fetch(subscription_id)
        return {
            "id": subscription["id"],
            "plan_id": subscription.get("plan_id"),
            "status": subscription.get("status"),
            "current_start": subscription.get("current_start"),
            "current_end": subscription.get("current_end"),
            "charge_at": subscription.get("charge_at"),
            "total_count": subscription.get("total_count"),
            "paid_count": subscription.get("paid_count"),
            "remaining_count": subscription.get("remaining_count"),
            "ended_at": subscription.get("ended_at"),
        }
    except Exception as exc:
        logger.error("Failed to fetch subscription %s: %s", subscription_id, exc)
        raise


# ─── One-Time Payments ───────────────────────────────────────────────────────


async def create_one_time_payment(
    user_id: uuid.UUID,
    amount: int,
    description: str,
    *,
    currency: str = "INR",
    customer_email: str | None = None,
    customer_name: str | None = None,
    customer_phone: str | None = None,
) -> dict[str, Any]:
    """Create a Razorpay payment link for a one-time purchase.

    Args:
        user_id: Internal user UUID.
        amount: Amount in **paise** (e.g. 10000 = ₹100).
        description: Human-readable description of the purchase.
        currency: Currency code (default ``"INR"``).
        customer_email: Optional customer email.
        customer_name: Optional customer name.
        customer_phone: Optional customer phone.

    Returns:
        Dict with ``payment_link_id``, ``short_url``, and ``amount``.
    """
    client = _get_client()

    payment_link_data: dict[str, Any] = {
        "amount": amount,
        "currency": currency,
        "description": description,
        "notes": {
            "user_id": str(user_id),
            "type": "one_time",
        },
    }

    if customer_email or customer_name or customer_phone:
        customer: dict[str, str] = {}
        if customer_name:
            customer["name"] = customer_name
        if customer_email:
            customer["email"] = customer_email
        if customer_phone:
            customer["contact"] = customer_phone
        payment_link_data["customer"] = customer

    try:
        link = client.payment_link.create(payment_link_data)
    except Exception as exc:
        logger.error("One-time payment creation failed for user %s: %s", user_id, exc)
        raise

    logger.info(
        "Created one-time payment link %s for user %s (₹%s)",
        link.get("id"),
        user_id,
        amount / 100,
    )

    return {
        "payment_link_id": link["id"],
        "short_url": link.get("short_url", ""),
        "amount": amount,
        "currency": currency,
        "status": link.get("status", "created"),
    }


# ─── Webhook Signature Verification ──────────────────────────────────────────


async def verify_webhook_signature(
    body: bytes,
    signature: str,
    webhook_secret: str | None = None,
) -> bool:
    """Verify a Razorpay webhook payload signature.

    Args:
        body: Raw request body bytes.
        signature: Value of the ``X-Razorpay-Signature`` header.
        webhook_secret: Webhook secret from Razorpay dashboard.
                        Falls back to ``RAZORPAY_WEBHOOK_SECRET`` env var.

    Returns:
        ``True`` if the signature is valid.
    """
    secret = webhook_secret or os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    if not secret:
        logger.warning("No webhook secret configured — skipping verification")
        return False

    try:
        expected = hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
    except Exception as exc:
        logger.error("Webhook signature verification failed: %s", exc)
        return False


# ─── GST-Compliant Invoice Generation ────────────────────────────────────────


async def generate_invoice(
    subscription: dict[str, Any],
    user: dict[str, Any],
    *,
    company_gstin: str | None = None,
    company_name: str = "IndiaMART Lead Manager",
    company_address: str = "",
) -> dict[str, Any]:
    """Generate a GST-compliant invoice data dict.

    Args:
        subscription: Subscription details (must include ``plan``, ``amount``,
                      ``razorpay_subscription_id``, ``starts_at``, ``expires_at``).
        user: User details (must include ``name``, ``email``, ``company_name``).
        company_gstin: Seller's GSTIN (set via ``COMPANY_GSTIN`` env var if not provided).
        company_name: Seller's company/brand name.
        company_address: Seller's registered address.

    Returns:
        Dict containing the full invoice data including GST breakdown.
    """
    seller_gstin = company_gstin or os.getenv("COMPANY_GSTIN", "")

    amount = subscription.get("amount", 0)
    # If amount is in paise, convert to rupees
    if amount > 10000:  # heuristic: likely paise
        amount_rupees = amount / 100
    else:
        amount_rupees = float(amount)

    # GST calculation (amount is inclusive or exclusive based on config)
    # Assuming amount is exclusive of GST
    base_amount = round(amount_rupees, 2)
    gst_amount = round(base_amount * GST_RATE, 2)
    total_amount = round(base_amount + gst_amount, 2)

    # Determine CGST/SGST vs IGST based on state (simplified: always IGST for now)
    igst = gst_amount
    cgst = 0.0
    sgst = 0.0

    invoice_number = f"INV-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"

    invoice: dict[str, Any] = {
        "invoice_number": invoice_number,
        "invoice_date": datetime.now(timezone.utc).isoformat(),
        "due_date": datetime.now(timezone.utc).isoformat(),

        # Seller details
        "seller": {
            "name": company_name,
            "gstin": seller_gstin,
            "address": company_address,
        },

        # Buyer details
        "buyer": {
            "name": user.get("name", ""),
            "email": user.get("email", ""),
            "company": user.get("company_name", ""),
            "gstin": user.get("gstin", ""),  # Buyer's GSTIN if B2B
        },

        # Line items
        "items": [
            {
                "description": f"IndiaMART Lead Manager — {subscription.get('plan', 'pro').capitalize()} Plan (Monthly)",
                "hsn_code": HSN_CODE,
                "quantity": 1,
                "unit_price": base_amount,
                "amount": base_amount,
            }
        ],

        # Tax breakdown
        "tax": {
            "hsn_code": HSN_CODE,
            "gst_rate": GST_RATE * 100,  # 18%
            "taxable_amount": base_amount,
            "cgst": cgst,
            "sgst": sgst,
            "igst": igst,
            "total_tax": gst_amount,
        },

        # Totals
        "subtotal": base_amount,
        "tax_total": gst_amount,
        "total": total_amount,
        "currency": "INR",

        # References
        "razorpay_subscription_id": subscription.get("razorpay_subscription_id", ""),
        "razorpay_payment_id": subscription.get("razorpay_payment_id", ""),
        "plan": subscription.get("plan", ""),
        "period": {
            "start": str(subscription.get("starts_at", "")),
            "end": str(subscription.get("expires_at", "")),
        },

        # Compliance
        "place_of_supply": "Internet / Pan-India",
        "reverse_charge": False,
        "notes": "This is a computer-generated invoice and does not require a signature.",
    }

    logger.info("Generated invoice %s for user %s", invoice_number, user.get("email"))
    return invoice
