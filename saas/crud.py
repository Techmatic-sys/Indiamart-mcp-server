"""
Async CRUD operations for the IndiaMART Lead Manager SaaS platform.

Every function accepts an ``AsyncSession`` and is fully user-scoped
(multi-tenant safe).
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import Date, and_, cast, delete, desc, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from saas.models import AutoReply, Lead, Subscription, SyncLog, User
from saas.schemas import (
    DailyCount,
    LeadListResponse,
    LeadResponse,
    StatsResponse,
    SubscriptionCreate,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  User CRUD
# ═══════════════════════════════════════════════════════════════════════════════


async def create_user(
    db: AsyncSession,
    *,
    email: str,
    password_hash: str,
    name: str,
    company_name: str | None = None,
    phone: str | None = None,
    indiamart_api_key: str | None = None,
    indiamart_glid: str | None = None,
) -> User:
    """Insert a new user and return the ORM instance."""
    user = User(
        email=email,
        password_hash=password_hash,
        name=name,
        company_name=company_name,
        phone=phone,
        indiamart_api_key=indiamart_api_key,
        indiamart_glid=indiamart_glid,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    """Look up a user by email address."""
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    """Look up a user by primary key."""
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def update_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    **fields: object,
) -> User | None:
    """Partially update a user's profile fields.

    Only non-``None`` keyword arguments are applied.
    """
    clean = {k: v for k, v in fields.items() if v is not None}
    if not clean:
        return await get_user_by_id(db, user_id)
    await db.execute(update(User).where(User.id == user_id).values(**clean))
    await db.flush()
    return await get_user_by_id(db, user_id)


# ═══════════════════════════════════════════════════════════════════════════════
#  Lead CRUD
# ═══════════════════════════════════════════════════════════════════════════════


async def save_lead(db: AsyncSession, user_id: uuid.UUID, data: dict) -> Lead:
    """Insert a single lead for the given user.

    ``data`` should be a dict of column names → values (excluding ``id``
    and ``user_id``).
    """
    lead = Lead(user_id=user_id, **data)
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    return lead


async def save_leads_bulk(
    db: AsyncSession,
    user_id: uuid.UUID,
    leads_data: list[dict],
) -> int:
    """Bulk-upsert leads for a user (skip duplicates by ``unique_query_id``).

    Returns the number of rows actually inserted (new leads).
    """
    if not leads_data:
        return 0

    rows = [{**ld, "user_id": user_id} for ld in leads_data]
    stmt = (
        pg_insert(Lead)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["unique_query_id", "user_id"])
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount  # type: ignore[return-value]


async def get_leads_paginated(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    page: int = 1,
    page_size: int = 20,
    query_type: str | None = None,
    is_starred: bool | None = None,
    is_read: bool | None = None,
) -> LeadListResponse:
    """Return a paginated, user-scoped list of leads with optional filters."""
    conditions = [Lead.user_id == user_id]
    if query_type is not None:
        conditions.append(Lead.query_type == query_type)
    if is_starred is not None:
        conditions.append(Lead.is_starred == is_starred)
    if is_read is not None:
        conditions.append(Lead.is_read == is_read)

    where = and_(*conditions)

    # Total count
    total: int = (await db.execute(select(func.count()).select_from(Lead).where(where))).scalar_one()

    # Fetch page
    offset = (page - 1) * page_size
    result = await db.execute(
        select(Lead).where(where).order_by(desc(Lead.created_at)).offset(offset).limit(page_size)
    )
    leads = result.scalars().all()

    return LeadListResponse(
        leads=[LeadResponse.model_validate(l) for l in leads],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=max(1, math.ceil(total / page_size)),
    )


async def get_lead_by_id(
    db: AsyncSession,
    user_id: uuid.UUID,
    lead_id: uuid.UUID,
) -> Lead | None:
    """Fetch a single lead scoped to a user."""
    result = await db.execute(
        select(Lead).where(and_(Lead.id == lead_id, Lead.user_id == user_id))
    )
    return result.scalar_one_or_none()


async def search_leads(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    *,
    page: int = 1,
    page_size: int = 20,
) -> LeadListResponse:
    """Full-text search across lead name, email, company, product, and message."""
    pattern = f"%{query}%"
    conditions = and_(
        Lead.user_id == user_id,
        or_(
            Lead.sender_name.ilike(pattern),
            Lead.sender_email.ilike(pattern),
            Lead.sender_company.ilike(pattern),
            Lead.query_product_name.ilike(pattern),
            Lead.query_message.ilike(pattern),
            Lead.sender_city.ilike(pattern),
        ),
    )

    total: int = (await db.execute(select(func.count()).select_from(Lead).where(conditions))).scalar_one()
    offset = (page - 1) * page_size
    result = await db.execute(
        select(Lead).where(conditions).order_by(desc(Lead.created_at)).offset(offset).limit(page_size)
    )
    leads = result.scalars().all()

    return LeadListResponse(
        leads=[LeadResponse.model_validate(l) for l in leads],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=max(1, math.ceil(total / page_size)),
    )


async def get_lead_stats(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> dict[str, int]:
    """Quick counts: total, unread, starred, with-reply."""
    base = Lead.user_id == user_id
    total = (await db.execute(select(func.count()).select_from(Lead).where(base))).scalar_one()
    unread = (
        await db.execute(
            select(func.count()).select_from(Lead).where(and_(base, Lead.is_read == False))
        )
    ).scalar_one()
    starred = (
        await db.execute(
            select(func.count()).select_from(Lead).where(and_(base, Lead.is_starred == True))
        )
    ).scalar_one()
    replied = (
        await db.execute(
            select(func.count()).select_from(Lead).where(and_(base, Lead.ai_reply_sent == True))
        )
    ).scalar_one()
    return {"total": total, "unread": unread, "starred": starred, "replied": replied}


# ═══════════════════════════════════════════════════════════════════════════════
#  Subscription CRUD
# ═══════════════════════════════════════════════════════════════════════════════


async def create_subscription(
    db: AsyncSession,
    user_id: uuid.UUID,
    data: SubscriptionCreate,
) -> Subscription:
    """Create a subscription record and update the user's plan."""
    sub = Subscription(
        user_id=user_id,
        plan=data.plan,
        razorpay_subscription_id=data.razorpay_subscription_id,
        razorpay_payment_id=data.razorpay_payment_id,
        amount=data.amount,
        currency=data.currency,
        status="active",
        starts_at=data.starts_at,
        expires_at=data.expires_at,
    )
    db.add(sub)

    # Upgrade user plan
    await db.execute(
        update(User)
        .where(User.id == user_id)
        .values(plan=data.plan, plan_expires_at=data.expires_at)
    )
    await db.flush()
    await db.refresh(sub)
    return sub


async def get_active_subscription(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> Subscription | None:
    """Return the currently active subscription for a user, if any."""
    result = await db.execute(
        select(Subscription)
        .where(
            and_(
                Subscription.user_id == user_id,
                Subscription.status == "active",
            )
        )
        .order_by(desc(Subscription.created_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def cancel_subscription(
    db: AsyncSession,
    user_id: uuid.UUID,
    subscription_id: uuid.UUID,
) -> Subscription | None:
    """Mark a subscription as cancelled and downgrade user to free plan."""
    await db.execute(
        update(Subscription)
        .where(
            and_(
                Subscription.id == subscription_id,
                Subscription.user_id == user_id,
            )
        )
        .values(status="cancelled")
    )
    await db.execute(
        update(User)
        .where(User.id == user_id)
        .values(plan="free", plan_expires_at=None)
    )
    await db.flush()

    result = await db.execute(
        select(Subscription).where(Subscription.id == subscription_id)
    )
    return result.scalar_one_or_none()


# ═══════════════════════════════════════════════════════════════════════════════
#  SyncLog CRUD
# ═══════════════════════════════════════════════════════════════════════════════


async def create_sync_log(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    sync_type: str,
    leads_fetched: int,
    leads_saved: int,
    status: str,
    error_message: str | None = None,
) -> SyncLog:
    """Record a sync operation."""
    log = SyncLog(
        user_id=user_id,
        sync_type=sync_type,
        leads_fetched=leads_fetched,
        leads_saved=leads_saved,
        status=status,
        error_message=error_message,
    )
    db.add(log)
    await db.flush()
    await db.refresh(log)
    return log


async def get_sync_logs(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    limit: int = 20,
) -> list[SyncLog]:
    """Return recent sync logs for a user, newest first."""
    result = await db.execute(
        select(SyncLog)
        .where(SyncLog.user_id == user_id)
        .order_by(desc(SyncLog.synced_at))
        .limit(limit)
    )
    return list(result.scalars().all())


# ═══════════════════════════════════════════════════════════════════════════════
#  Dashboard Stats
# ═══════════════════════════════════════════════════════════════════════════════


async def get_dashboard_stats(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> StatsResponse:
    """Compute aggregate dashboard statistics scoped to a single user."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())  # Monday
    month_start = today_start.replace(day=1)

    base = Lead.user_id == user_id

    # Total leads
    total: int = (
        await db.execute(select(func.count()).select_from(Lead).where(base))
    ).scalar_one()

    # Leads today
    leads_today: int = (
        await db.execute(
            select(func.count())
            .select_from(Lead)
            .where(and_(base, Lead.created_at >= today_start))
        )
    ).scalar_one()

    # Leads this week
    leads_week: int = (
        await db.execute(
            select(func.count())
            .select_from(Lead)
            .where(and_(base, Lead.created_at >= week_start))
        )
    ).scalar_one()

    # Leads this month
    leads_month: int = (
        await db.execute(
            select(func.count())
            .select_from(Lead)
            .where(and_(base, Lead.created_at >= month_start))
        )
    ).scalar_one()

    # Top cities (top 10)
    city_rows = (
        await db.execute(
            select(Lead.sender_city, func.count().label("cnt"))
            .where(and_(base, Lead.sender_city.isnot(None)))
            .group_by(Lead.sender_city)
            .order_by(desc("cnt"))
            .limit(10)
        )
    ).all()
    top_cities = [{"city": r[0], "count": r[1]} for r in city_rows]

    # Top products (top 10)
    product_rows = (
        await db.execute(
            select(Lead.query_product_name, func.count().label("cnt"))
            .where(and_(base, Lead.query_product_name.isnot(None)))
            .group_by(Lead.query_product_name)
            .order_by(desc("cnt"))
            .limit(10)
        )
    ).all()
    top_products = [{"product": r[0], "count": r[1]} for r in product_rows]

    # Daily counts (last 30 days)
    thirty_days_ago = today_start - timedelta(days=30)
    daily_rows = (
        await db.execute(
            select(
                cast(Lead.created_at, Date).label("day"),
                func.count().label("cnt"),
            )
            .where(and_(base, Lead.created_at >= thirty_days_ago))
            .group_by("day")
            .order_by("day")
        )
    ).all()
    daily_counts = [DailyCount(date=str(r[0]), count=r[1]) for r in daily_rows]

    # Query type breakdown
    qt_rows = (
        await db.execute(
            select(Lead.query_type, func.count().label("cnt"))
            .where(and_(base, Lead.query_type.isnot(None)))
            .group_by(Lead.query_type)
        )
    ).all()
    query_type_breakdown = {r[0]: r[1] for r in qt_rows}

    return StatsResponse(
        total_leads=total,
        leads_today=leads_today,
        leads_week=leads_week,
        leads_month=leads_month,
        top_cities=top_cities,
        top_products=top_products,
        daily_counts=daily_counts,
        query_type_breakdown=query_type_breakdown,
    )
