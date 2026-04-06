"""
Background scheduler for per-user IndiaMART lead syncing.

Uses APScheduler's ``AsyncIOScheduler`` to run staggered sync jobs
based on each user's subscription plan.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from saas.database import async_session_factory
from saas.models import User
from saas.services.sync_service import SyncResult, sync_user_leads

logger = logging.getLogger(__name__)

# ─── Plan-based intervals (minutes) ─────────────────────────────────────────

PLAN_INTERVALS: dict[str, int] = {
    "free": 30,
    "pro": 10,
    "business": 5,
}

DEFAULT_INTERVAL = 30  # fallback

# ─── Stagger offset to avoid thundering-herd on the API ─────────────────────

_STAGGER_STEP_SECONDS = 10  # each user is offset by this many seconds
_user_counter: int = 0

# ─── Scheduler singleton ────────────────────────────────────────────────────

_scheduler: AsyncIOScheduler | None = None


def _get_scheduler() -> AsyncIOScheduler:
    """Return (or create) the singleton scheduler."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(
            job_defaults={
                "coalesce": True,          # skip missed runs
                "max_instances": 1,        # one sync per user at a time
                "misfire_grace_time": 120,
            },
        )
    return _scheduler


def _job_id(user_id: uuid.UUID) -> str:
    """Deterministic job ID for a given user."""
    return f"sync_user_{user_id}"


async def _run_sync_job(user_id: str, api_key: str) -> None:
    """Wrapper executed by APScheduler for each scheduled sync."""
    uid = uuid.UUID(user_id)
    try:
        result: SyncResult = await sync_user_leads(uid, api_key, hours=24, sync_type="auto")
        if not result.success:
            logger.warning("Scheduled sync failed for user %s: %s", user_id, result.errors)
    except Exception:  # noqa: BLE001
        logger.exception("Unhandled exception in scheduled sync for user %s", user_id)


# ─── Public API ──────────────────────────────────────────────────────────────


async def start_scheduler() -> None:
    """Start the scheduler and load all active users with valid API keys.

    Call this once during application startup (e.g. FastAPI lifespan).
    """
    scheduler = _get_scheduler()

    if scheduler.running:
        logger.info("Scheduler already running — skipping start")
        return

    # Load active users
    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(
                User.is_active.is_(True),
                User.indiamart_api_key.isnot(None),
                User.indiamart_api_key != "",
            )
        )
        users: list[User] = list(result.scalars().all())

    global _user_counter
    _user_counter = 0

    for user in users:
        _add_job(scheduler, user)

    scheduler.start()
    logger.info("Scheduler started with %d user sync jobs", len(users))


async def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    scheduler = _get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def _add_job(scheduler: AsyncIOScheduler, user: User) -> None:
    """Internal: add a sync job for a user with plan-based interval + stagger."""
    global _user_counter

    interval_minutes = PLAN_INTERVALS.get(user.plan, DEFAULT_INTERVAL)
    stagger_seconds = (_user_counter * _STAGGER_STEP_SECONDS) % (interval_minutes * 60)
    _user_counter += 1

    job_id = _job_id(user.id)

    # Remove existing job if present (idempotent add)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    scheduler.add_job(
        _run_sync_job,
        trigger=IntervalTrigger(
            minutes=interval_minutes,
            start_date=datetime.now(timezone.utc),
            jitter=stagger_seconds,
        ),
        id=job_id,
        name=f"sync-{user.email}",
        kwargs={
            "user_id": str(user.id),
            "api_key": user.indiamart_api_key,  # encrypted; decrypted inside sync_user_leads
        },
        replace_existing=True,
    )
    logger.debug(
        "Scheduled sync for user %s (plan=%s, every %d min, stagger %d s)",
        user.id,
        user.plan,
        interval_minutes,
        stagger_seconds,
    )


async def add_user_sync(user_id: uuid.UUID) -> bool:
    """Add (or update) a sync job for a user.

    Fetches the user from DB to get their plan and API key.

    Returns:
        ``True`` if the job was added, ``False`` if the user doesn't qualify.
    """
    scheduler = _get_scheduler()

    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

    if not user or not user.is_active or not user.indiamart_api_key:
        logger.warning("Cannot add sync for user %s — inactive or no API key", user_id)
        return False

    _add_job(scheduler, user)
    logger.info("Added/updated sync job for user %s", user_id)
    return True


async def remove_user_sync(user_id: uuid.UUID) -> bool:
    """Remove a user's sync job from the scheduler.

    Returns:
        ``True`` if removed, ``False`` if no job existed.
    """
    scheduler = _get_scheduler()
    job_id = _job_id(user_id)

    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info("Removed sync job for user %s", user_id)
        return True

    logger.debug("No sync job found for user %s — nothing to remove", user_id)
    return False


async def trigger_manual_sync(user_id: uuid.UUID) -> SyncResult:
    """Immediately trigger a sync for a user (manual sync).

    Bypasses the scheduler entirely and runs synchronously in the
    current async context.

    Returns:
        A :class:`SyncResult` with the outcome.
    """
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

    if not user:
        return SyncResult(user_id=user_id, success=False, errors=["User not found"])
    if not user.indiamart_api_key:
        return SyncResult(
            user_id=user_id, success=False, errors=["No IndiaMART API key configured"]
        )

    return await sync_user_leads(
        user_id=user.id,
        api_key=user.indiamart_api_key,
        hours=24,
        sync_type="manual",
    )


def get_scheduler_status() -> dict[str, Any]:
    """Return current scheduler state and all registered jobs.

    Returns:
        Dict with ``running``, ``job_count``, and ``jobs`` list.
    """
    scheduler = _get_scheduler()

    jobs_info: list[dict[str, Any]] = []
    for job in scheduler.get_jobs():
        jobs_info.append(
            {
                "id": job.id,
                "name": job.name,
                "next_run_time": (
                    job.next_run_time.isoformat() if job.next_run_time else None
                ),
                "trigger": str(job.trigger),
            }
        )

    return {
        "running": scheduler.running,
        "job_count": len(jobs_info),
        "jobs": jobs_info,
    }
