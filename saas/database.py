"""
Async database engine, session factory, and FastAPI dependency.

Uses SQLAlchemy 2.0 async API with asyncpg as the PostgreSQL driver.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from saas.config import settings
from saas.models import Base

# ─── Engine & Session Factory ────────────────────────────────────────────────

# Build engine kwargs — SQLite doesn't support pool_size/max_overflow
_engine_kwargs: dict = {"echo": False}
if "sqlite" not in settings.DATABASE_URL:
    _engine_kwargs.update(pool_size=20, max_overflow=10, pool_pre_ping=True)

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Alias for convenience (used in health checks etc.)
async_session = async_session_factory


# ─── FastAPI Dependency ──────────────────────────────────────────────────────


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session for FastAPI dependency injection.

    Usage::

        @app.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ─── Init ────────────────────────────────────────────────────────────────────


async def init_db() -> None:
    """Create all tables defined in the ORM models.

    Call once at application startup (e.g. in a FastAPI ``lifespan`` handler).
    For production, prefer Alembic migrations instead.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
