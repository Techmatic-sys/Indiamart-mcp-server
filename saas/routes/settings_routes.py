"""
User Settings API routes for LeadFlow CRM.

Provides endpoints to get and update extended business settings
(business details, bank info, GST/PAN, monthly targets).
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from saas.auth import get_current_active_user
from saas.database import get_db
from saas.models import User, UserSettings

router = APIRouter(prefix="/api/settings", tags=["settings"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class UserSettingsResponse(BaseModel):
    id: str
    user_id: str
    company_address: Optional[str] = None
    company_city: Optional[str] = None
    company_state: Optional[str] = None
    company_pincode: Optional[str] = None
    gst_number: Optional[str] = None
    pan_number: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account: Optional[str] = None
    bank_ifsc: Optional[str] = None
    logo_url: Optional[str] = None
    monthly_revenue_target: Optional[float] = None
    monthly_lead_target: Optional[int] = None


class UpdateSettingsRequest(BaseModel):
    company_address: Optional[str] = Field(None, max_length=1000)
    company_city: Optional[str] = Field(None, max_length=100)
    company_state: Optional[str] = Field(None, max_length=100)
    company_pincode: Optional[str] = Field(None, max_length=10)
    gst_number: Optional[str] = Field(None, max_length=20)
    pan_number: Optional[str] = Field(None, max_length=15)
    bank_name: Optional[str] = Field(None, max_length=200)
    bank_account: Optional[str] = Field(None, max_length=50)
    bank_ifsc: Optional[str] = Field(None, max_length=15)
    logo_url: Optional[str] = Field(None, max_length=500)
    monthly_revenue_target: Optional[float] = Field(None, ge=0)
    monthly_lead_target: Optional[int] = Field(None, ge=0)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def get_or_create_settings(user_id: str, db: AsyncSession) -> UserSettings:
    """Fetch existing settings or create a blank record."""
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = UserSettings(
            id=str(uuid.uuid4()),
            user_id=user_id,
        )
        db.add(settings)
        await db.flush()
    return settings


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", summary="Get current user's business settings")
async def get_settings(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    settings = await get_or_create_settings(current_user.id, db)
    await db.commit()
    return {
        "settings": UserSettingsResponse(
            id=settings.id,
            user_id=settings.user_id,
            company_address=settings.company_address,
            company_city=settings.company_city,
            company_state=settings.company_state,
            company_pincode=settings.company_pincode,
            gst_number=settings.gst_number,
            pan_number=settings.pan_number,
            bank_name=settings.bank_name,
            bank_account=settings.bank_account,
            bank_ifsc=settings.bank_ifsc,
            logo_url=settings.logo_url,
            monthly_revenue_target=settings.monthly_revenue_target,
            monthly_lead_target=settings.monthly_lead_target,
        )
    }


@router.put("", summary="Update current user's business settings")
async def update_settings(
    body: UpdateSettingsRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    settings = await get_or_create_settings(current_user.id, db)

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(settings, field, value)

    await db.commit()
    await db.refresh(settings)

    return {
        "message": "Settings updated successfully",
        "settings": UserSettingsResponse(
            id=settings.id,
            user_id=settings.user_id,
            company_address=settings.company_address,
            company_city=settings.company_city,
            company_state=settings.company_state,
            company_pincode=settings.company_pincode,
            gst_number=settings.gst_number,
            pan_number=settings.pan_number,
            bank_name=settings.bank_name,
            bank_account=settings.bank_account,
            bank_ifsc=settings.bank_ifsc,
            logo_url=settings.logo_url,
            monthly_revenue_target=settings.monthly_revenue_target,
            monthly_lead_target=settings.monthly_lead_target,
        )
    }
