"""
Pydantic v2 schemas for request/response validation.

All schemas use ``model_config = ConfigDict(from_attributes=True)`` so they
can be constructed directly from SQLAlchemy model instances.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ═══════════════════════════════════════════════════════════════════════════════
#  User
# ═══════════════════════════════════════════════════════════════════════════════


class UserCreate(BaseModel):
    """Payload for registering a new user."""

    email: EmailStr
    password: str = Field(..., min_length=8, description="Plain-text password (hashed server-side)")
    name: str = Field(..., min_length=1, max_length=255)
    company_name: str | None = None
    phone: str | None = None
    indiamart_api_key: str | None = Field(None, description="IndiaMART CRM API key")
    indiamart_glid: str | None = None


class UserLogin(BaseModel):
    """Payload for email + password login."""

    email: EmailStr
    password: str


class UserResponse(BaseModel):
    """Public user representation (never exposes password_hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    company_name: str | None = None
    phone: str | None = None
    indiamart_glid: str | None = None
    plan: str
    plan_expires_at: datetime | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserUpdate(BaseModel):
    """Partial-update payload for user profile."""

    name: str | None = None
    company_name: str | None = None
    phone: str | None = None
    indiamart_api_key: str | None = None
    indiamart_glid: str | None = None


# ═══════════════════════════════════════════════════════════════════════════════
#  Lead
# ═══════════════════════════════════════════════════════════════════════════════


class LeadResponse(BaseModel):
    """Single lead detail."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    unique_query_id: str
    query_type: str | None = None
    query_time: datetime | None = None
    sender_name: str | None = None
    sender_mobile: str | None = None
    sender_email: str | None = None
    subject: str | None = None
    sender_company: str | None = None
    sender_address: str | None = None
    sender_city: str | None = None
    sender_state: str | None = None
    sender_pincode: str | None = None
    sender_country: str | None = None
    query_product_name: str | None = None
    query_message: str | None = None
    call_duration: str | None = None
    receiver_mobile: str | None = None
    ai_reply_sent: bool = False
    ai_reply_text: str | None = None
    lead_score: int | None = None
    is_read: bool = False
    is_starred: bool = False
    notes: str | None = None
    created_at: datetime


class LeadListResponse(BaseModel):
    """Paginated list of leads."""

    leads: list[LeadResponse]
    total: int = Field(..., description="Total leads matching the query")
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1)
    total_pages: int = Field(..., ge=0)


# ═══════════════════════════════════════════════════════════════════════════════
#  Subscription
# ═══════════════════════════════════════════════════════════════════════════════


class SubscriptionCreate(BaseModel):
    """Payload for creating a subscription record after Razorpay checkout."""

    plan: str = Field(..., pattern=r"^(free|pro|business)$")
    razorpay_subscription_id: str | None = None
    razorpay_payment_id: str | None = None
    amount: float
    currency: str = "INR"
    starts_at: datetime
    expires_at: datetime


class SubscriptionResponse(BaseModel):
    """Subscription detail."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    plan: str
    razorpay_subscription_id: str | None = None
    razorpay_payment_id: str | None = None
    amount: float
    currency: str
    status: str
    starts_at: datetime
    expires_at: datetime
    created_at: datetime


# ═══════════════════════════════════════════════════════════════════════════════
#  SyncLog
# ═══════════════════════════════════════════════════════════════════════════════


class SyncLogResponse(BaseModel):
    """Sync log entry."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    sync_type: str
    leads_fetched: int
    leads_saved: int
    status: str
    error_message: str | None = None
    synced_at: datetime


# ═══════════════════════════════════════════════════════════════════════════════
#  Dashboard / Stats
# ═══════════════════════════════════════════════════════════════════════════════


class DailyCount(BaseModel):
    """Leads received on a single day."""

    date: str = Field(..., description="ISO date string (YYYY-MM-DD)")
    count: int


class StatsResponse(BaseModel):
    """Aggregated dashboard statistics (user-scoped)."""

    total_leads: int
    leads_today: int
    leads_week: int
    leads_month: int
    top_cities: list[dict[str, int | str]] = Field(
        default_factory=list,
        description='List of {"city": str, "count": int}',
    )
    top_products: list[dict[str, int | str]] = Field(
        default_factory=list,
        description='List of {"product": str, "count": int}',
    )
    daily_counts: list[DailyCount] = Field(default_factory=list)
    query_type_breakdown: dict[str, int] = Field(
        default_factory=dict,
        description="e.g. {'W': 120, 'B': 45}",
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  Plan Info
# ═══════════════════════════════════════════════════════════════════════════════


class PlanLimitsSchema(BaseModel):
    """Resource limits for a single plan."""

    max_leads: int
    auto_sync: bool
    ai_replies: bool
    whatsapp_notifications: bool


class PlanInfo(BaseModel):
    """Public description of a subscription plan."""

    name: str
    price: float = Field(..., description="Monthly price in INR")
    limits: PlanLimitsSchema
