"""
IndiaMART Lead Manager — SaaS Database Layer.

Multi-tenant database models, schemas, CRUD operations, and configuration
for the IndiaMART Lead Manager SaaS platform.
"""

from saas.config import settings, PLAN_LIMITS
from saas.database import get_db, init_db, engine, async_session_factory
from saas.models import Base, User, Lead, Subscription, SyncLog, AutoReply

__all__ = [
    "settings",
    "PLAN_LIMITS",
    "get_db",
    "init_db",
    "engine",
    "async_session_factory",
    "Base",
    "User",
    "Lead",
    "Subscription",
    "SyncLog",
    "AutoReply",
]
