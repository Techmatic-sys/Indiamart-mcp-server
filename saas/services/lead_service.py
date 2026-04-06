"""
Lead business-logic service.

Provides paginated queries, dashboard statistics, full-text search,
CSV export, and lead-management helpers — all scoped to a single
tenant (``user_id``).
"""

from __future__ import annotations

import csv
import io
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import String, and_, cast, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from saas.database import async_session_factory
from saas.models import Lead

logger = logging.getLogger(__name__)

# IST timezone
IST = timezone(timedelta(hours=5, minutes=30))


# ─── Paginated Lead Listing ─────────────────────────────────────────────────


async def get_user_leads(
    user_id: uuid.UUID,
    page: int = 1,
    per_page: int = 25,
    filters: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Return paginated, filterable leads for a user.

    Args:
        user_id: Tenant user UUID.
        page: 1-indexed page number.
        per_page: Items per page (max 100).
        filters: Optional dict with keys:
            ``city``, ``product``, ``date_from``, ``date_to``,
            ``search``, ``starred``, ``unread``, ``query_type``.

    Returns:
        Dict with ``leads``, ``total``, ``page``, ``per_page``, ``pages``.
    """
    filters = filters or {}
    per_page = min(max(per_page, 1), 100)
    offset = (max(page, 1) - 1) * per_page

    async with async_session_factory() as session:
        base = select(Lead).where(Lead.user_id == user_id)
        count_q = select(func.count()).select_from(Lead).where(Lead.user_id == user_id)

        conditions = _build_filter_conditions(filters)
        if conditions:
            base = base.where(and_(*conditions))
            count_q = count_q.where(and_(*conditions))

        # Total count
        total = (await session.execute(count_q)).scalar() or 0

        # Fetch page
        stmt = base.order_by(Lead.query_time.desc().nullslast(), Lead.created_at.desc())
        stmt = stmt.offset(offset).limit(per_page)
        rows = (await session.execute(stmt)).scalars().all()

        pages = max((total + per_page - 1) // per_page, 1)

        return {
            "leads": [_lead_to_dict(lead) for lead in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": pages,
        }


# ─── Dashboard Stats ────────────────────────────────────────────────────────


async def get_user_stats(user_id: uuid.UUID) -> dict[str, Any]:
    """Return dashboard statistics for a user.

    Includes: total, today, this_week, this_month, top_cities,
    top_products, daily_trend (last 30 days), type_breakdown.
    """
    now = datetime.now(IST)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)
    trend_start = today_start - timedelta(days=30)

    async with async_session_factory() as session:
        user_filter = Lead.user_id == user_id

        # Total
        total = (
            await session.execute(
                select(func.count()).select_from(Lead).where(user_filter)
            )
        ).scalar() or 0

        # Today
        today_count = (
            await session.execute(
                select(func.count())
                .select_from(Lead)
                .where(user_filter, Lead.query_time >= today_start)
            )
        ).scalar() or 0

        # This week
        week_count = (
            await session.execute(
                select(func.count())
                .select_from(Lead)
                .where(user_filter, Lead.query_time >= week_start)
            )
        ).scalar() or 0

        # This month
        month_count = (
            await session.execute(
                select(func.count())
                .select_from(Lead)
                .where(user_filter, Lead.query_time >= month_start)
            )
        ).scalar() or 0

        # Top cities (top 10)
        top_cities_q = (
            select(Lead.sender_city, func.count().label("cnt"))
            .where(user_filter, Lead.sender_city.isnot(None), Lead.sender_city != "")
            .group_by(Lead.sender_city)
            .order_by(func.count().desc())
            .limit(10)
        )
        top_cities = [
            {"city": row[0], "count": row[1]}
            for row in (await session.execute(top_cities_q)).all()
        ]

        # Top products (top 10)
        top_products_q = (
            select(Lead.query_product_name, func.count().label("cnt"))
            .where(
                user_filter,
                Lead.query_product_name.isnot(None),
                Lead.query_product_name != "",
            )
            .group_by(Lead.query_product_name)
            .order_by(func.count().desc())
            .limit(10)
        )
        top_products = [
            {"product": row[0], "count": row[1]}
            for row in (await session.execute(top_products_q)).all()
        ]

        # Daily trend (last 30 days) — use date() for SQLite compatibility
        day_expr = func.date(Lead.query_time)
        daily_trend_q = (
            select(
                day_expr.label("day"),
                func.count().label("cnt"),
            )
            .where(user_filter, Lead.query_time >= trend_start)
            .group_by(day_expr)
            .order_by(day_expr)
        )
        daily_trend = [
            {
                "date": str(row[0]) if row[0] else None,
                "count": row[1],
            }
            for row in (await session.execute(daily_trend_q)).all()
        ]

        # Type breakdown
        type_q = (
            select(Lead.query_type, func.count().label("cnt"))
            .where(user_filter, Lead.query_type.isnot(None))
            .group_by(Lead.query_type)
            .order_by(func.count().desc())
        )
        type_breakdown = [
            {"type": row[0], "count": row[1]}
            for row in (await session.execute(type_q)).all()
        ]

        # Unread count
        unread = (
            await session.execute(
                select(func.count())
                .select_from(Lead)
                .where(user_filter, Lead.is_read.is_(False))
            )
        ).scalar() or 0

        # Starred count
        starred = (
            await session.execute(
                select(func.count())
                .select_from(Lead)
                .where(user_filter, Lead.is_starred.is_(True))
            )
        ).scalar() or 0

    return {
        "total": total,
        "today": today_count,
        "this_week": week_count,
        "this_month": month_count,
        "unread": unread,
        "starred": starred,
        "top_cities": top_cities,
        "top_products": top_products,
        "daily_trend": daily_trend,
        "type_breakdown": type_breakdown,
    }


# ─── Full-Text Search ───────────────────────────────────────────────────────


async def search_user_leads(
    user_id: uuid.UUID,
    keyword: str,
    page: int = 1,
    per_page: int = 25,
) -> dict[str, Any]:
    """Search leads by keyword across name, email, company, product, message, city.

    Returns the same paginated structure as :func:`get_user_leads`.
    """
    per_page = min(max(per_page, 1), 100)
    offset = (max(page, 1) - 1) * per_page
    pattern = f"%{keyword}%"

    search_filter = or_(
        Lead.sender_name.ilike(pattern),
        Lead.sender_email.ilike(pattern),
        Lead.sender_company.ilike(pattern),
        Lead.query_product_name.ilike(pattern),
        Lead.query_message.ilike(pattern),
        Lead.sender_city.ilike(pattern),
        Lead.sender_mobile.ilike(pattern),
        Lead.subject.ilike(pattern),
    )

    async with async_session_factory() as session:
        base = select(Lead).where(Lead.user_id == user_id, search_filter)
        count_q = (
            select(func.count())
            .select_from(Lead)
            .where(Lead.user_id == user_id, search_filter)
        )

        total = (await session.execute(count_q)).scalar() or 0
        stmt = base.order_by(Lead.query_time.desc().nullslast()).offset(offset).limit(per_page)
        rows = (await session.execute(stmt)).scalars().all()

        pages = max((total + per_page - 1) // per_page, 1)

        return {
            "leads": [_lead_to_dict(lead) for lead in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": pages,
        }


# ─── CSV Export ──────────────────────────────────────────────────────────────

CSV_COLUMNS = [
    "unique_query_id",
    "query_type",
    "query_time",
    "sender_name",
    "sender_mobile",
    "sender_email",
    "sender_company",
    "sender_city",
    "sender_state",
    "query_product_name",
    "query_message",
    "subject",
    "is_read",
    "is_starred",
    "notes",
]


async def export_user_leads_csv(
    user_id: uuid.UUID,
    filters: Optional[dict[str, Any]] = None,
) -> str:
    """Export leads matching the given filters as a CSV string.

    Returns:
        A UTF-8 CSV string ready to be served as a download.
    """
    filters = filters or {}

    async with async_session_factory() as session:
        stmt = select(Lead).where(Lead.user_id == user_id)

        conditions = _build_filter_conditions(filters)
        if conditions:
            stmt = stmt.where(and_(*conditions))

        stmt = stmt.order_by(Lead.query_time.desc().nullslast())
        rows = (await session.execute(stmt)).scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(CSV_COLUMNS)

    for lead in rows:
        writer.writerow(
            [
                getattr(lead, col, "")
                if not isinstance(getattr(lead, col, None), datetime)
                else getattr(lead, col).isoformat()
                for col in CSV_COLUMNS
            ]
        )

    return output.getvalue()


# ─── Lead Management ────────────────────────────────────────────────────────


async def get_lead_by_id(
    user_id: uuid.UUID,
    lead_id: uuid.UUID,
) -> dict[str, Any] | None:
    """Fetch a single lead by ID, scoped to the user."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(Lead).where(Lead.id == lead_id, Lead.user_id == user_id)
        )
        lead = result.scalar_one_or_none()
        return _lead_to_dict(lead) if lead else None


async def mark_lead_read(
    user_id: uuid.UUID,
    lead_id: uuid.UUID,
) -> bool:
    """Mark a lead as read. Returns ``True`` if updated."""
    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                update(Lead)
                .where(Lead.id == lead_id, Lead.user_id == user_id)
                .values(is_read=True)
            )
            return result.rowcount > 0  # type: ignore[return-value]


async def star_lead(
    user_id: uuid.UUID,
    lead_id: uuid.UUID,
) -> bool | None:
    """Toggle a lead's starred status. Returns new value or ``None`` if not found."""
    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                select(Lead).where(Lead.id == lead_id, Lead.user_id == user_id)
            )
            lead = result.scalar_one_or_none()
            if not lead:
                return None
            lead.is_starred = not lead.is_starred
            return lead.is_starred


async def add_lead_note(
    user_id: uuid.UUID,
    lead_id: uuid.UUID,
    note: str,
) -> bool:
    """Append a note to a lead (overwrites existing). Returns ``True`` if updated."""
    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                update(Lead)
                .where(Lead.id == lead_id, Lead.user_id == user_id)
                .values(notes=note)
            )
            return result.rowcount > 0  # type: ignore[return-value]


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _build_filter_conditions(filters: dict[str, Any]) -> list[Any]:
    """Translate a filters dict into SQLAlchemy WHERE conditions."""
    conditions: list[Any] = []

    if city := filters.get("city"):
        conditions.append(Lead.sender_city.ilike(f"%{city}%"))

    if product := filters.get("product"):
        conditions.append(Lead.query_product_name.ilike(f"%{product}%"))

    if date_from := filters.get("date_from"):
        if isinstance(date_from, str):
            date_from = datetime.fromisoformat(date_from)
        conditions.append(Lead.query_time >= date_from)

    if date_to := filters.get("date_to"):
        if isinstance(date_to, str):
            date_to = datetime.fromisoformat(date_to)
        conditions.append(Lead.query_time <= date_to)

    if search := filters.get("search"):
        pattern = f"%{search}%"
        conditions.append(
            or_(
                Lead.sender_name.ilike(pattern),
                Lead.sender_email.ilike(pattern),
                Lead.sender_company.ilike(pattern),
                Lead.query_product_name.ilike(pattern),
                Lead.query_message.ilike(pattern),
                Lead.sender_city.ilike(pattern),
            )
        )

    if filters.get("starred") is True:
        conditions.append(Lead.is_starred.is_(True))

    if filters.get("unread") is True:
        conditions.append(Lead.is_read.is_(False))

    if query_type := filters.get("query_type"):
        conditions.append(Lead.query_type == query_type)

    return conditions


def _lead_to_dict(lead: Lead) -> dict[str, Any]:
    """Serialise a Lead ORM instance to a JSON-safe dict."""
    return {
        "id": str(lead.id),
        "unique_query_id": lead.unique_query_id,
        "query_type": lead.query_type,
        "query_time": lead.query_time.isoformat() if lead.query_time else None,
        "sender_name": lead.sender_name,
        "sender_mobile": lead.sender_mobile,
        "sender_email": lead.sender_email,
        "subject": lead.subject,
        "sender_company": lead.sender_company,
        "sender_address": lead.sender_address,
        "sender_city": lead.sender_city,
        "sender_state": lead.sender_state,
        "sender_pincode": lead.sender_pincode,
        "sender_country": lead.sender_country,
        "query_product_name": lead.query_product_name,
        "query_message": lead.query_message,
        "call_duration": lead.call_duration,
        "receiver_mobile": lead.receiver_mobile,
        "ai_reply_sent": lead.ai_reply_sent,
        "ai_reply_text": lead.ai_reply_text,
        "lead_score": lead.lead_score,
        "is_read": lead.is_read,
        "is_starred": lead.is_starred,
        "notes": lead.notes,
        "lead_stage": getattr(lead, "lead_stage", "new") or "new",
        "deal_value": getattr(lead, "deal_value", None),
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
    }
