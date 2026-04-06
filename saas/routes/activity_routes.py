"""
Lead activity log API endpoints.

Track calls, emails, meetings, and notes against individual leads.
All routes require authentication via ``get_current_active_user``.
Mounted under ``/api`` by the main FastAPI application.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from saas.auth import get_current_active_user
from saas.database import async_session_factory
from saas.models import Activity, Lead, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["activities"])

VALID_ACTIVITY_TYPES = {"call", "email", "meeting", "note", "whatsapp", "sms", "follow_up", "other"}

# ─── Request Schemas ─────────────────────────────────────────────────────────


class ActivityCreateRequest(BaseModel):
    """Body for creating an activity log entry."""

    activity_type: str = Field(..., description="Type of activity")
    content: str = Field(..., min_length=1, max_length=5000, description="Activity description or notes")


# ─── Dependency shorthand ────────────────────────────────────────────────────

CurrentUser = Depends(get_current_active_user)


# ─── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/leads/{lead_id}/activities", status_code=status.HTTP_201_CREATED)
async def create_activity(
    lead_id: uuid.UUID,
    body: ActivityCreateRequest,
    user: User = CurrentUser,
) -> dict[str, Any]:
    """Add an activity log entry to a lead.

    Args:
        lead_id: UUID of the lead.
        body: Activity type and content.
        user: Authenticated user (must own the lead).

    Returns:
        The created activity record.

    Raises:
        HTTPException 400: If the activity_type is invalid.
        HTTPException 404: If the lead is not found.
    """
    if body.activity_type not in VALID_ACTIVITY_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid activity_type '{body.activity_type}'. Must be one of: {', '.join(sorted(VALID_ACTIVITY_TYPES))}",
        )

    async with async_session_factory() as session:
        # Verify lead belongs to user
        lead_result = await session.execute(
            select(Lead).where(Lead.id == str(lead_id), Lead.user_id == user.id)
        )
        lead = lead_result.scalar_one_or_none()

        if lead is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

        activity = Activity(
            user_id=user.id,
            lead_id=str(lead_id),
            activity_type=body.activity_type,
            content=body.content,
            created_at=datetime.now(timezone.utc),
        )
        session.add(activity)
        await session.commit()
        await session.refresh(activity)

    logger.info("Activity %s created for lead %s by user %s", activity.id, lead_id, user.id)

    return {
        "id": str(activity.id),
        "lead_id": str(lead_id),
        "activity_type": activity.activity_type,
        "content": activity.content,
        "created_at": activity.created_at.isoformat() if activity.created_at else None,
        "user_id": str(user.id),
    }


@router.get("/leads/{lead_id}/activities")
async def list_activities(
    lead_id: uuid.UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: User = CurrentUser,
) -> dict[str, Any]:
    """List activity log entries for a lead, newest first.

    Args:
        lead_id: UUID of the lead.
        page: Page number (1-indexed).
        per_page: Results per page.
        user: Authenticated user (must own the lead).

    Returns:
        Paginated list of activity records.

    Raises:
        HTTPException 404: If the lead is not found.
    """
    async with async_session_factory() as session:
        # Verify lead belongs to user
        lead_result = await session.execute(
            select(Lead).where(Lead.id == str(lead_id), Lead.user_id == user.id)
        )
        lead = lead_result.scalar_one_or_none()

        if lead is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

        offset = (page - 1) * per_page

        total = (
            await session.execute(
                select(func.count())
                .select_from(Activity)
                .where(Activity.lead_id == str(lead_id), Activity.user_id == user.id)
            )
        ).scalar() or 0

        rows = (
            await session.execute(
                select(Activity)
                .where(Activity.lead_id == str(lead_id), Activity.user_id == user.id)
                .order_by(Activity.created_at.desc())
                .offset(offset)
                .limit(per_page)
            )
        ).scalars().all()

    activities = [
        {
            "id": str(a.id),
            "lead_id": str(a.lead_id),
            "activity_type": a.activity_type,
            "content": a.content,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "user_id": str(a.user_id),
        }
        for a in rows
    ]

    return {
        "activities": activities,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max((total + per_page - 1) // per_page, 1),
    }
