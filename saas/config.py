"""
SaaS configuration — environment variables and plan limits.

All settings are loaded from environment variables with sensible defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from dotenv import load_dotenv

# Load .env from saas directory
load_dotenv(dotenv_path=Path(__file__).parent / ".env")


@dataclass(frozen=True)
class PlanLimits:
    """Resource limits for a subscription plan."""

    max_leads: int
    auto_sync: bool
    ai_replies: bool
    whatsapp_notifications: bool


@dataclass(frozen=True)
class Settings:
    """Application-wide settings loaded from environment variables."""

    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "sqlite+aiosqlite:///./saas_leads.db",
    )

    # Redis (for caching / rate-limiting / Celery broker)
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-production")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
        os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
    )

    # Razorpay
    RAZORPAY_KEY_ID: str = os.getenv("RAZORPAY_KEY_ID", "")
    RAZORPAY_KEY_SECRET: str = os.getenv("RAZORPAY_KEY_SECRET", "")


# Singleton settings instance
settings = Settings()

# Plan limits keyed by plan name
PLAN_LIMITS: dict[str, PlanLimits] = {
    "free": PlanLimits(
        max_leads=50,
        auto_sync=False,
        ai_replies=False,
        whatsapp_notifications=False,
    ),
    "pro": PlanLimits(
        max_leads=5_000,
        auto_sync=True,
        ai_replies=True,
        whatsapp_notifications=False,
    ),
    "business": PlanLimits(
        max_leads=50_000,
        auto_sync=True,
        ai_replies=True,
        whatsapp_notifications=True,
    ),
}
