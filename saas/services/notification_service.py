"""
Notification Service — WhatsApp, Email, and SMS delivery.

Each channel has a stub implementation that logs the message and returns
success.  Real API call structures (Gupshup, Resend, Twilio) are included
as commented code for easy activation.
"""

from __future__ import annotations

import logging
import os
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

logger = logging.getLogger(__name__)


# ─── Result DTO ──────────────────────────────────────────────────────────────


@dataclass
class NotificationResult:
    """Outcome of a notification dispatch attempt."""

    success: bool
    channel: str
    message: str
    provider: str | None = None
    error: str | None = None


# ─── WhatsApp ────────────────────────────────────────────────────────────────


async def send_whatsapp_notification(
    phone: str,
    message: str,
) -> NotificationResult:
    """Send a WhatsApp message to the given phone number.

    **Current implementation:** stub that logs the message and returns success.
    Uncomment the Gupshup block below to switch to a live provider.

    Args:
        phone: Recipient phone number (with country code, e.g. ``919876543210``).
        message: Message body.

    Returns:
        :class:`NotificationResult` with delivery status.
    """

    # ── Gupshup API (uncomment to activate) ───────────────────────────────
    # import httpx
    #
    # GUPSHUP_API_KEY = os.getenv("GUPSHUP_API_KEY", "")
    # GUPSHUP_APP_NAME = os.getenv("GUPSHUP_APP_NAME", "")
    # GUPSHUP_SOURCE_NUMBER = os.getenv("GUPSHUP_SOURCE_NUMBER", "")
    #
    # url = "https://api.gupshup.io/wa/api/v1/msg"
    # headers = {"apikey": GUPSHUP_API_KEY}
    # payload = {
    #     "channel": "whatsapp",
    #     "source": GUPSHUP_SOURCE_NUMBER,
    #     "destination": phone,
    #     "message": json.dumps({"type": "text", "text": message}),
    #     "src.name": GUPSHUP_APP_NAME,
    # }
    #
    # try:
    #     async with httpx.AsyncClient() as client:
    #         resp = await client.post(url, data=payload, headers=headers)
    #         resp.raise_for_status()
    #         return NotificationResult(
    #             success=True,
    #             channel="whatsapp",
    #             message=f"Sent to {phone}",
    #             provider="gupshup",
    #         )
    # except Exception as exc:
    #     logger.exception("Gupshup WhatsApp send failed")
    #     return NotificationResult(
    #         success=False,
    #         channel="whatsapp",
    #         message=f"Failed to send to {phone}",
    #         provider="gupshup",
    #         error=str(exc),
    #     )

    # ── Twilio WhatsApp (alternative, uncomment to activate) ──────────────
    # from twilio.rest import Client as TwilioClient
    #
    # TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
    # TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
    # TWILIO_WA_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
    #
    # try:
    #     client = TwilioClient(TWILIO_SID, TWILIO_TOKEN)
    #     client.messages.create(
    #         body=message,
    #         from_=TWILIO_WA_FROM,
    #         to=f"whatsapp:+{phone}",
    #     )
    #     return NotificationResult(
    #         success=True,
    #         channel="whatsapp",
    #         message=f"Sent to {phone}",
    #         provider="twilio",
    #     )
    # except Exception as exc:
    #     logger.exception("Twilio WhatsApp send failed")
    #     return NotificationResult(
    #         success=False,
    #         channel="whatsapp",
    #         message=f"Failed to send to {phone}",
    #         provider="twilio",
    #         error=str(exc),
    #     )

    # ── Stub implementation ───────────────────────────────────────────────
    logger.info(
        "WhatsApp stub → phone=%s message=%s",
        phone,
        message[:80],
    )
    return NotificationResult(
        success=True,
        channel="whatsapp",
        message=f"[STUB] WhatsApp sent to {phone}",
        provider="stub",
    )


# ─── Email ───────────────────────────────────────────────────────────────────


async def send_email_notification(
    to_email: str,
    subject: str,
    body: str,
) -> NotificationResult:
    """Send an email notification.

    **Current implementation:** uses ``smtplib`` with env-configured SMTP
    credentials.  Falls back to a logging stub when ``SMTP_HOST`` is not set.
    Uncomment the Resend block for an HTTP-API alternative.

    Args:
        to_email: Recipient email address.
        subject: Email subject line.
        body: Plain-text email body.

    Returns:
        :class:`NotificationResult` with delivery status.
    """

    # ── Resend API (uncomment to activate) ────────────────────────────────
    # import httpx
    #
    # RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
    # RESEND_FROM = os.getenv("RESEND_FROM_EMAIL", "noreply@yourdomain.com")
    #
    # try:
    #     async with httpx.AsyncClient() as client:
    #         resp = await client.post(
    #             "https://api.resend.com/emails",
    #             headers={
    #                 "Authorization": f"Bearer {RESEND_API_KEY}",
    #                 "Content-Type": "application/json",
    #             },
    #             json={
    #                 "from": RESEND_FROM,
    #                 "to": [to_email],
    #                 "subject": subject,
    #                 "text": body,
    #             },
    #         )
    #         resp.raise_for_status()
    #         return NotificationResult(
    #             success=True,
    #             channel="email",
    #             message=f"Sent to {to_email}",
    #             provider="resend",
    #         )
    # except Exception as exc:
    #     logger.exception("Resend email send failed")
    #     return NotificationResult(
    #         success=False,
    #         channel="email",
    #         message=f"Failed to send to {to_email}",
    #         provider="resend",
    #         error=str(exc),
    #     )

    smtp_host = os.getenv("SMTP_HOST", "")

    if smtp_host:
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER", "")
        smtp_pass = os.getenv("SMTP_PASS", "")
        smtp_from = os.getenv("SMTP_FROM", smtp_user)

        try:
            msg = MIMEMultipart()
            msg["From"] = smtp_from
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                if smtp_user and smtp_pass:
                    server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_from, [to_email], msg.as_string())

            logger.info("Email sent via SMTP to %s", to_email)
            return NotificationResult(
                success=True,
                channel="email",
                message=f"Sent to {to_email}",
                provider="smtp",
            )
        except Exception as exc:
            logger.exception("SMTP email send failed")
            return NotificationResult(
                success=False,
                channel="email",
                message=f"Failed to send to {to_email}",
                provider="smtp",
                error=str(exc),
            )

    # ── Stub fallback ────────────────────────────────────────────────────
    logger.info(
        "Email stub → to=%s subject=%s body=%s",
        to_email,
        subject,
        body[:80],
    )
    return NotificationResult(
        success=True,
        channel="email",
        message=f"[STUB] Email sent to {to_email}",
        provider="stub",
    )


# ─── SMS ─────────────────────────────────────────────────────────────────────


async def send_sms_notification(
    phone: str,
    message: str,
) -> NotificationResult:
    """Send an SMS notification via Twilio.

    **Current implementation:** stub that logs the message.
    Uncomment the Twilio block to activate.

    Args:
        phone: Recipient phone number (with country code).
        message: SMS body (max ~160 chars for single segment).

    Returns:
        :class:`NotificationResult` with delivery status.
    """

    # ── Twilio SMS (uncomment to activate) ────────────────────────────────
    # from twilio.rest import Client as TwilioClient
    #
    # TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
    # TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
    # TWILIO_SMS_FROM = os.getenv("TWILIO_SMS_FROM", "")
    #
    # try:
    #     client = TwilioClient(TWILIO_SID, TWILIO_TOKEN)
    #     client.messages.create(
    #         body=message,
    #         from_=TWILIO_SMS_FROM,
    #         to=f"+{phone}",
    #     )
    #     return NotificationResult(
    #         success=True,
    #         channel="sms",
    #         message=f"Sent to {phone}",
    #         provider="twilio",
    #     )
    # except Exception as exc:
    #     logger.exception("Twilio SMS send failed")
    #     return NotificationResult(
    #         success=False,
    #         channel="sms",
    #         message=f"Failed to send to {phone}",
    #         provider="twilio",
    #         error=str(exc),
    #     )

    # ── Stub ──────────────────────────────────────────────────────────────
    logger.info("SMS stub → phone=%s message=%s", phone, message[:80])
    return NotificationResult(
        success=True,
        channel="sms",
        message=f"[STUB] SMS sent to {phone}",
        provider="stub",
    )


# ─── Orchestrator ────────────────────────────────────────────────────────────


async def notify_new_lead(
    user: dict[str, Any],
    lead: dict[str, Any],
) -> list[NotificationResult]:
    """Send new-lead notifications based on the user's preferences.

    Checks the user's ``notification_preferences`` dict for channel toggles
    (``whatsapp_enabled``, ``email_enabled``) and dispatches accordingly.

    Args:
        user: User dict containing at least ``email``, ``phone``, and
            ``notification_preferences``.
        lead: Lead dict with standard IndiaMART fields.

    Returns:
        List of :class:`NotificationResult` — one per channel attempted.
    """
    results: list[NotificationResult] = []
    prefs: dict[str, Any] = user.get("notification_preferences") or {}

    buyer_name = lead.get("sender_name") or "A buyer"
    product = lead.get("query_product_name") or "your product"
    city = lead.get("sender_city") or ""

    short_msg = (
        f"🔔 New Lead: {buyer_name} enquired about {product}"
        + (f" from {city}" if city else "")
    )

    # WhatsApp
    if prefs.get("whatsapp_enabled") and user.get("phone"):
        result = await send_whatsapp_notification(user["phone"], short_msg)
        results.append(result)
        logger.info(
            "WhatsApp notification for user %s: %s",
            user.get("email", "?"),
            "OK" if result.success else result.error,
        )

    # Email
    if prefs.get("email_enabled") and user.get("email"):
        email_subject = f"New Lead: {buyer_name} — {product}"
        email_body = (
            f"Hi {user.get('name', 'there')},\n\n"
            f"You have a new lead on IndiaMART Lead Manager.\n\n"
            f"Buyer: {buyer_name}\n"
            f"Product: {product}\n"
            f"City: {city}\n"
            f"Message: {lead.get('query_message', 'N/A')}\n\n"
            f"Log in to your dashboard to view the full details and respond.\n\n"
            f"— IndiaMART Lead Manager"
        )
        result = await send_email_notification(
            user["email"], email_subject, email_body
        )
        results.append(result)
        logger.info(
            "Email notification for user %s: %s",
            user["email"],
            "OK" if result.success else result.error,
        )

    if not results:
        logger.info(
            "No notification channels enabled for user %s",
            user.get("email", "?"),
        )

    return results
