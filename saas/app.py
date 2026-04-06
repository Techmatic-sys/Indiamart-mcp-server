"""
LeadFlow CRM — Main FastAPI Application.

Entry point for the web server. Wires up routers, middleware, static files,
frontend page serving, health checks, and lifecycle events.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from saas.database import init_db
from saas.middleware import (
    RateLimitMiddleware,
    RequestLoggingMiddleware,
    configure_cors,
)
from saas.routes.auth_routes import router as auth_router
from saas.routes.lead_routes import router as lead_router
from saas.routes.ai_routes import router as ai_router
from saas.routes.payment_routes import router as payment_router
from saas.routes.pipeline_routes import router as pipeline_router
from saas.routes.reply_routes import router as reply_router
from saas.routes.briefing_routes import router as briefing_router
from saas.routes.settings_routes import router as settings_router
from saas.routes.analytics_routes import router as analytics_router
from saas.routes.catalog_routes import router as catalog_router
from saas.services.scheduler import (
    get_scheduler_status,
    start_scheduler,
    stop_scheduler,
)

logger = logging.getLogger(__name__)

__version__ = "2.0.0"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup / shutdown lifecycle."""
    logger.info("🚀 Starting LeadFlow CRM v%s", __version__)

    # Startup
    await init_db()
    logger.info("✅ Database initialised")

    await start_scheduler()
    logger.info("✅ Scheduler started")

    yield

    # Shutdown
    await stop_scheduler()
    logger.info("🛑 Scheduler stopped — goodbye!")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="LeadFlow CRM",
    description="AI-Powered CRM platform for managing IndiaMART leads",
    version=__version__,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# ---------------------------------------------------------------------------
# Middleware (order matters — outermost first)
# ---------------------------------------------------------------------------

configure_cors(app)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RateLimitMiddleware)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(auth_router, tags=["Authentication"])
app.include_router(lead_router, tags=["Leads"])
app.include_router(ai_router, tags=["AI"])
app.include_router(payment_router, tags=["Payments"])
app.include_router(pipeline_router, tags=["Pipeline"])
app.include_router(reply_router, tags=["AI Reply Composer"])
app.include_router(briefing_router, tags=["Briefing & ROI"])
app.include_router(settings_router, tags=["Settings"])
app.include_router(analytics_router, tags=["Analytics"])
app.include_router(catalog_router, tags=["Catalog"])

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

# ---------------------------------------------------------------------------
# Frontend page routes
# ---------------------------------------------------------------------------


@app.get("/manifest.json", include_in_schema=False)
async def serve_manifest() -> FileResponse:
    """Serve PWA manifest."""
    return FileResponse(FRONTEND_DIR / "manifest.json", media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
async def serve_sw_root() -> FileResponse:
    """Serve service worker from root (needed for max scope)."""
    return FileResponse(FRONTEND_DIR / "sw.js", media_type="application/javascript")


@app.get("/", include_in_schema=False)
async def root_landing() -> FileResponse:
    """Serve the landing page at root URL."""
    return _serve_page("landing.html")


def _serve_page(filename: str):
    """Return a FileResponse for a frontend HTML file."""
    filepath = FRONTEND_DIR / filename
    if not filepath.is_file():
        return JSONResponse(
            status_code=404,
            content={"detail": f"Page not found: {filename}"},
        )
    return FileResponse(filepath, media_type="text/html")


@app.get("/app/login", include_in_schema=False)
async def page_login() -> FileResponse:
    return _serve_page("login.html")


@app.get("/app/signup", include_in_schema=False)
async def page_signup() -> FileResponse:
    return _serve_page("signup.html")


@app.get("/app/dashboard", include_in_schema=False)
async def page_dashboard() -> FileResponse:
    return _serve_page("dashboard.html")


@app.get("/app/leads", include_in_schema=False)
async def page_leads() -> FileResponse:
    return _serve_page("leads.html")


@app.get("/app/pipeline", include_in_schema=False)
async def page_pipeline() -> FileResponse:
    return _serve_page("pipeline.html")


@app.get("/app/analytics", include_in_schema=False)
async def page_analytics() -> FileResponse:
    return _serve_page("analytics.html")


@app.get("/app/settings", include_in_schema=False)
async def page_settings() -> FileResponse:
    return _serve_page("settings.html")


@app.get("/app/billing", include_in_schema=False)
async def page_billing() -> FileResponse:
    return _serve_page("billing.html")


@app.get("/app/forecast", include_in_schema=False)
async def page_forecast() -> FileResponse:
    return _serve_page("forecast.html")


@app.get("/app/briefing", include_in_schema=False)
async def page_briefing() -> FileResponse:
    return _serve_page("briefing.html")


@app.get("/app/briefing.html", include_in_schema=False)
async def page_briefing_html():
    return RedirectResponse(url="/app/briefing", status_code=302)


@app.get("/app/catalog", include_in_schema=False)
async def page_catalog() -> FileResponse:
    return _serve_page("catalog.html")


@app.get("/app/quotations", include_in_schema=False)
async def page_quotations() -> FileResponse:
    return _serve_page("quotations.html")


# .html aliases (frontend JS may redirect to these)
@app.get("/app/login.html", include_in_schema=False)
async def page_login_html():
    return RedirectResponse(url="/app/login", status_code=302)

@app.get("/app/signup.html", include_in_schema=False)
async def page_signup_html():
    return RedirectResponse(url="/app/signup", status_code=302)

@app.get("/app/dashboard.html", include_in_schema=False)
async def page_dashboard_html():
    return RedirectResponse(url="/app/dashboard", status_code=302)

@app.get("/app/leads.html", include_in_schema=False)
async def page_leads_html():
    return RedirectResponse(url="/app/leads", status_code=302)

@app.get("/app/pipeline.html", include_in_schema=False)
async def page_pipeline_html():
    return RedirectResponse(url="/app/pipeline", status_code=302)

@app.get("/app/analytics.html", include_in_schema=False)
async def page_analytics_html():
    return RedirectResponse(url="/app/analytics", status_code=302)

@app.get("/app/settings.html", include_in_schema=False)
async def page_settings_html():
    return RedirectResponse(url="/app/settings", status_code=302)

@app.get("/app/billing.html", include_in_schema=False)
async def page_billing_html():
    return RedirectResponse(url="/app/billing", status_code=302)

# Also serve from root path (some frontend JS redirects to /login.html etc.)
@app.get("/login.html", include_in_schema=False)
async def root_login_html():
    return RedirectResponse(url="/app/login", status_code=302)

@app.get("/login", include_in_schema=False)
async def root_login():
    return RedirectResponse(url="/app/login", status_code=302)

@app.get("/signup.html", include_in_schema=False)
async def root_signup_html():
    return RedirectResponse(url="/app/signup", status_code=302)

@app.get("/dashboard.html", include_in_schema=False)
async def root_dashboard_html():
    return RedirectResponse(url="/app/dashboard", status_code=302)

@app.get("/dashboard", include_in_schema=False)
async def root_dashboard():
    return RedirectResponse(url="/app/dashboard", status_code=302)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/api/health", tags=["System"])
async def health_check() -> JSONResponse:
    """Returns service health including DB connectivity and scheduler status."""
    from sqlalchemy import text
    from saas.database import async_session

    # Database check
    db_status = "healthy"
    db_detail: str | None = None
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        db_status = "unhealthy"
        db_detail = str(exc)

    # Scheduler check
    scheduler_info = get_scheduler_status()

    overall = "healthy" if db_status == "healthy" else "degraded"

    payload = {
        "status": overall,
        "version": __version__,
        "database": {
            "status": db_status,
            **({"detail": db_detail} if db_detail else {}),
        },
        "scheduler": scheduler_info,
    }

    status_code = 200 if overall == "healthy" else 503
    return JSONResponse(content=payload, status_code=status_code)


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------


@app.exception_handler(404)
async def not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    """Custom 404 handler."""
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=404,
            content={"detail": "Resource not found"},
        )
    # For non-API routes, redirect to dashboard (SPA-style)
    return RedirectResponse(url="/app/dashboard", status_code=302)


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Custom 500 handler."""
    logger.exception("Unhandled server error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error. Please try again later.",
        },
    )


# ---------------------------------------------------------------------------
# Dev entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "saas.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
