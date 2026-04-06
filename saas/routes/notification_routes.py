"""
In-app notification API endpoints.

Deliver and manage user notifications.
All routes require authentication via ``get_current_active_user``.
Mounted under ``/api`` by the main FastAPI application.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from saas.auth import get_current_active_user
from saas.database import async_session_factory
from saas.models import Notification, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["notifications"])

# ─── Dependency shorthand ────────────────────────────────────────────────────

CurrentUser = Depends(get_current_active_user)


# ─── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/notifications")
async def list_notifications(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: User = CurrentUser,
) -> dict[str, Any]:
    """List notifications for the authenticated user, newest first.

    Args:
        page: Page number (1-indexed).
        per_page: Results per page.
        user: Authenticated user.

    Returns:
        Paginated list of notification records.
    """
    offset = (page - 1) * per_page

    async with async_session_factory() as session:
        total = (
            await session.execute(
                select(func.count())
                .select_from(Notification)
                .where(Notification.user_id == user.id)
            )
        ).scalar() or 0

        rows = (
            await session.execute(
                select(Notification)
                .where(Notification.user_id == user.id)
                .order_by(Notification.created_at.desc())
                .offset(offset)
                .limit(per_page)
            )
        ).scalars().all()

    notifications = [_notification_to_dict(n) for n in rows]

    return {
        "notifications": notifications,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max((total + per_page - 1) // per_page, 1),
    }


@router.get("/notifications/unread-count")
async def unread_count(user: User = CurrentUser) -> dict[str, int]:
    """Return the count of unread notifications for the authenticated user.

    Returns:
        ``{"count": N}``
    """
    async with async_session_factory() as session:
        count = (
            await session.execute(
                select(func.count())
                .select_from(Notification)
                .where(Notification.user_id == user.id, Notification.is_read == False)  # noqa: E712
            )
        ).scalar() or 0

    return {"count": count}


@router.put("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: uuid.UUID,
    user: User = CurrentUser,
) -> dict[str, Any]:
    """Mark a single notification as read.

    Args:
        notification_id: UUID of the notification.
        user: Authenticated user (must own the notification).

    Returns:
        Updated notification record.

    Raises:
        HTTPException 404: If the notification is not found.
    """
    async with async_session_factory() as session:
        result = await session.execute(
            select(Notification).where(
                Notification.id == str(notification_id),
                Notification.user_id == user.id,
            )
        )
        notification = result.scalar_one_or_none()

        if notification is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found"
            )

        notification.is_read = True
        await session.commit()
        await session.refresh(notification)

    return _notification_to_dict(notification)


@router.post("/notifications/read-all")
async def mark_all_read(user: User = CurrentUser) -> dict[str, Any]:
    """Mark all unread notifications as read for the authenticated user.

    Returns:
        Count of notifications that were updated.
    """
    async with async_session_factory() as session:
        # Count unread first
        unread = (
            await session.execute(
                select(func.count())
                .select_from(Notification)
                .where(Notification.user_id == user.id, Notification.is_read == False)  # noqa: E712
            )
        ).scalar() or 0

        if unread > 0:
            await session.execute(
                update(Notification)
                .where(Notification.user_id == user.id, Notification.is_read == False)  # noqa: E712
                .values(is_read=True)
            )
            await session.commit()

    logger.info("Marked %d notifications as read for user %s", unread, user.id)

    return {"success": True, "updated": unread}


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _notification_to_dict(notification: Notification) -> dict[str, Any]:
    """Serialize a Notification ORM object to a dict."""
    return {
        "id": str(notification.id),
        "user_id": str(notification.user_id),
        "lead_id": str(notification.lead_id) if getattr(notification, "lead_id", None) else None,
        "title": getattr(notification, "title", None),
        "message": getattr(notification, "message", None),
        "notification_type": getattr(notification, "notification_type", None),
        "is_read": notification.is_read,
        "created_at": notification.created_at.isoformat() if notification.created_at else None,
    }
