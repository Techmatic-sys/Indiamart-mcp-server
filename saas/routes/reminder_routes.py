"""
Reminder / follow-up API endpoints.

Create and manage time-based reminders linked to leads.
All routes require authentication via ``get_current_active_user``.
Mounted under ``/api`` by the main FastAPI application.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from saas.auth import get_current_active_user
from saas.database import async_session_factory
from saas.models import Lead, Reminder, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["reminders"])

# ─── Request Schemas ─────────────────────────────────────────────────────────


class ReminderCreateRequest(BaseModel):
    """Body for creating a new reminder."""

    lead_id: Optional[str] = Field(None, description="Optional lead UUID to attach the reminder to")
    remind_at: datetime = Field(..., description="When to trigger the reminder (ISO 8601)")
    message: str = Field(..., min_length=1, max_length=1000, description="Reminder message text")


# ─── Dependency shorthand ────────────────────────────────────────────────────

CurrentUser = Depends(get_current_active_user)


# ─── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/reminders", status_code=status.HTTP_201_CREATED)
async def create_reminder(
    body: ReminderCreateRequest,
    user: User = CurrentUser,
) -> dict[str, Any]:
    """Create a new reminder for the authenticated user.

    Args:
        body: Reminder details including optional lead link, time, and message.
        user: Authenticated user.

    Returns:
        The created reminder record.

    Raises:
        HTTPException 400: If lead_id is provided but the lead doesn't exist or belong to user.
    """
    async with async_session_factory() as session:
        # Validate lead_id if provided
        if body.lead_id:
            lead_result = await session.execute(
                select(Lead).where(Lead.id == body.lead_id, Lead.user_id == user.id)
            )
            if lead_result.scalar_one_or_none() is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Lead not found or does not belong to you",
                )

        reminder = Reminder(
            user_id=user.id,
            lead_id=body.lead_id,
            remind_at=body.remind_at,
            message=body.message,
            is_done=False,
            created_at=datetime.now(timezone.utc),
        )
        session.add(reminder)
        await session.commit()
        await session.refresh(reminder)

    logger.info("Reminder %s created for user %s", reminder.id, user.id)

    return _reminder_to_dict(reminder)


@router.get("/reminders")
async def list_reminders(
    filter: Optional[str] = Query(None, description="Filter: upcoming, overdue, done"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: User = CurrentUser,
) -> dict[str, Any]:
    """List reminders for the authenticated user.

    Args:
        filter: Optional filter — ``upcoming`` (future, not done), ``overdue`` (past, not done),
                or ``done`` (completed).
        page: Page number (1-indexed).
        per_page: Results per page.
        user: Authenticated user.

    Returns:
        Paginated list of reminder records.
    """
    now = datetime.now(timezone.utc)
    offset = (page - 1) * per_page

    async with async_session_factory() as session:
        base_query = select(Reminder).where(Reminder.user_id == user.id)
        count_query = select(func.count()).select_from(Reminder).where(Reminder.user_id == user.id)

        if filter == "upcoming":
            base_query = base_query.where(Reminder.remind_at > now, Reminder.is_done == False)  # noqa: E712
            count_query = count_query.where(Reminder.remind_at > now, Reminder.is_done == False)  # noqa: E712
        elif filter == "overdue":
            base_query = base_query.where(Reminder.remind_at <= now, Reminder.is_done == False)  # noqa: E712
            count_query = count_query.where(Reminder.remind_at <= now, Reminder.is_done == False)  # noqa: E712
        elif filter == "done":
            base_query = base_query.where(Reminder.is_done == True)  # noqa: E712
            count_query = count_query.where(Reminder.is_done == True)  # noqa: E712

        total = (await session.execute(count_query)).scalar() or 0

        rows = (
            await session.execute(
                base_query
                .order_by(Reminder.remind_at.asc())
                .offset(offset)
                .limit(per_page)
            )
        ).scalars().all()

    reminders = [_reminder_to_dict(r) for r in rows]

    return {
        "reminders": reminders,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max((total + per_page - 1) // per_page, 1),
        "filter": filter,
    }


@router.put("/reminders/{reminder_id}/done")
async def mark_reminder_done(
    reminder_id: uuid.UUID,
    user: User = CurrentUser,
) -> dict[str, Any]:
    """Mark a reminder as completed.

    Args:
        reminder_id: UUID of the reminder.
        user: Authenticated user (must own the reminder).

    Returns:
        Updated reminder record.

    Raises:
        HTTPException 404: If the reminder is not found.
    """
    async with async_session_factory() as session:
        result = await session.execute(
            select(Reminder).where(
                Reminder.id == str(reminder_id), Reminder.user_id == user.id
            )
        )
        reminder = result.scalar_one_or_none()

        if reminder is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reminder not found")

        reminder.is_done = True
        reminder.done_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(reminder)

    return _reminder_to_dict(reminder)


@router.delete("/reminders/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reminder(
    reminder_id: uuid.UUID,
    user: User = CurrentUser,
) -> None:
    """Delete a reminder.

    Args:
        reminder_id: UUID of the reminder.
        user: Authenticated user (must own the reminder).

    Raises:
        HTTPException 404: If the reminder is not found.
    """
    async with async_session_factory() as session:
        result = await session.execute(
            select(Reminder).where(
                Reminder.id == str(reminder_id), Reminder.user_id == user.id
            )
        )
        reminder = result.scalar_one_or_none()

        if reminder is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reminder not found")

        await session.delete(reminder)
        await session.commit()

    logger.info("Reminder %s deleted by user %s", reminder_id, user.id)


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _reminder_to_dict(reminder: Reminder) -> dict[str, Any]:
    """Serialize a Reminder ORM object to a dict."""
    return {
        "id": str(reminder.id),
        "user_id": str(reminder.user_id),
        "lead_id": str(reminder.lead_id) if reminder.lead_id else None,
        "remind_at": reminder.remind_at.isoformat() if reminder.remind_at else None,
        "message": reminder.message,
        "is_done": reminder.is_done,
        "done_at": reminder.done_at.isoformat() if getattr(reminder, "done_at", None) else None,
        "created_at": reminder.created_at.isoformat() if reminder.created_at else None,
    }
