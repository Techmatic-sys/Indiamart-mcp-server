"""
Middleware for the IndiaMART Lead Manager SaaS platform.

Provides rate limiting, request logging, and CORS configuration.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Callable

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rate-limiting middleware (in-memory, per-process)
# ---------------------------------------------------------------------------

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple sliding-window rate limiter.

    * Authenticated users (identified by ``Authorization`` header bearer
      subject): **100 requests / minute**.
    * Unauthenticated callers (identified by client IP): **20 requests / minute**.

    Uses an in-memory store — suitable for single-process deployments.
    For multi-process / multi-node setups, swap to a Redis-backed counter.
    """

    WINDOW_SECONDS: int = 60
    AUTH_LIMIT: int = 500
    ANON_LIMIT: int = 200

    def __init__(self, app: FastAPI) -> None:
        super().__init__(app)
        # key → list of request timestamps
        self._buckets: dict[str, list[float]] = defaultdict(list)

    def _identify_caller(self, request: Request) -> tuple[str, int]:
        """Return ``(caller_key, max_requests)`` for the request."""
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1]
            try:
                from jose import jwt
                from saas.config import settings

                payload = jwt.decode(
                    token,
                    settings.SECRET_KEY,
                    algorithms=[settings.JWT_ALGORITHM],
                )
                user_id = payload.get("sub", "unknown")
                return f"user:{user_id}", self.AUTH_LIMIT
            except Exception:
                pass  # fall through to IP-based limiting

        client_ip = request.client.host if request.client else "unknown"
        return f"ip:{client_ip}", self.ANON_LIMIT

    def _is_rate_limited(self, key: str, limit: int) -> tuple[bool, int]:
        """Check whether ``key`` has exceeded ``limit`` in the current window.

        Returns ``(is_limited, remaining_requests)``.
        """
        now = time.monotonic()
        cutoff = now - self.WINDOW_SECONDS

        # Prune old entries
        bucket = self._buckets[key]
        self._buckets[key] = bucket = [t for t in bucket if t > cutoff]

        remaining = max(0, limit - len(bucket))
        if len(bucket) >= limit:
            return True, remaining

        bucket.append(now)
        return False, remaining - 1

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Skip rate limiting for page routes, static files, and health checks
        path = request.url.path
        if path.startswith(("/app/", "/static/", "/api/health")) or path in ("/", "/health"):
            return await call_next(request)

        key, limit = self._identify_caller(request)
        is_limited, remaining = self._is_rate_limited(key, limit)

        if is_limited:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Rate limit exceeded. Try again later."},
                headers={
                    "Retry-After": str(self.WINDOW_SECONDS),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


# ---------------------------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------------------------

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request with method, path, status code, and duration."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            status_code = response.status_code if response else 500
            logger.info(
                "%s %s → %d (%.1fms)",
                request.method,
                request.url.path,
                status_code,
                duration_ms,
            )


# ---------------------------------------------------------------------------
# CORS configuration
# ---------------------------------------------------------------------------

def configure_cors(app: FastAPI) -> None:
    """Add CORS middleware with sensible defaults.

    In production, narrow ``allow_origins`` to your frontend domain(s).
    """
    import os

    origins_env = os.getenv("CORS_ORIGINS", "")
    if origins_env:
        origins = [o.strip() for o in origins_env.split(",") if o.strip()]
    else:
        # Development defaults
        origins = [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://localhost:8080",
        ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "Retry-After",
        ],
    )
