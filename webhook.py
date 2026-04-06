"""
IndiaMART Webhook Server — FastAPI Push API Receiver.

Receives real-time lead pushes from IndiaMART's Push API,
validates the payload, and saves leads to the local SQLite database.
Also serves REST API endpoints for the frontend dashboard.

Run with:
    uvicorn webhook:app --host 0.0.0.0 --port 8000
"""

import asyncio
import csv
import io
import logging
import math
import os
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, RedirectResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from config import PORT, WEBHOOK_SECRET, logger
from db.database import (
    init_db,
    save_lead,
    get_all_leads,
    get_leads_count,
    get_lead_by_query_id,
    get_leads_paginated,
    get_dashboard_stats,
    get_unique_cities,
    get_unique_products,
    get_filtered_leads_all,
)

webhook_logger = logging.getLogger("indiamart-mcp.webhook")

# Auto-sync interval (seconds) — IndiaMART allows 1 call per 5 minutes
AUTO_SYNC_INTERVAL = 5 * 60  # 5 minutes


async def _auto_sync_loop():
    """Background task: sync leads from IndiaMART every 5 minutes."""
    from tools.leads import sync_latest_leads
    # Wait 10 seconds after startup before first sync
    await asyncio.sleep(10)
    webhook_logger.info("Auto-sync started. Will sync every %d seconds.", AUTO_SYNC_INTERVAL)
    while True:
        try:
            webhook_logger.info("Auto-sync: fetching latest leads from IndiaMART...")
            result = await sync_latest_leads()
            webhook_logger.info("Auto-sync result: %s", result.replace('\n', ' '))
        except Exception as e:
            webhook_logger.error("Auto-sync error: %s", e)
        await asyncio.sleep(AUTO_SYNC_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the database on startup and start auto-sync."""
    await init_db()
    # Start auto-sync background task
    sync_task = asyncio.create_task(_auto_sync_loop())
    webhook_logger.info("Webhook server started. Database initialized. Auto-sync enabled.")
    yield
    # Cancel auto-sync on shutdown
    sync_task.cancel()
    webhook_logger.info("Webhook server shutting down.")


app = FastAPI(
    title="IndiaMART Webhook Receiver",
    description="Receives real-time lead pushes from IndiaMART's Push API.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware for frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────────────────────
# Existing endpoints (unchanged)
# ──────────────────────────────────────────────────────────────


@app.get("/")
async def root():
    """Redirect to dashboard UI."""
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard")
async def dashboard():
    """Serve the main dashboard page."""
    html_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    return FileResponse(html_path, media_type="text/html")


@app.get("/analytics")
@app.get("/analytics.html")
async def analytics_page():
    """Serve the analytics page."""
    html_path = os.path.join(os.path.dirname(__file__), "static", "analytics.html")
    return FileResponse(html_path, media_type="text/html")


@app.get("/index.html")
@app.get("/dashboard.html")
async def dashboard_html():
    """Serve dashboard via .html routes too."""
    html_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    return FileResponse(html_path, media_type="text/html")


@app.post("/indiamart-webhook")
async def receive_webhook(request: Request) -> JSONResponse:
    """Receive a lead push from IndiaMART.

    Validates the payload and saves the lead to the database.
    IndiaMART sends lead data as JSON in the request body.
    """
    try:
        payload: Any = await request.json()
    except Exception:
        webhook_logger.error("Failed to parse webhook JSON payload.")
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    # Optional: validate webhook secret if configured
    if WEBHOOK_SECRET:
        # Check for secret in header or query param
        provided_secret = request.headers.get("X-Webhook-Secret", "")
        if not provided_secret:
            provided_secret = request.query_params.get("secret", "")
        if provided_secret != WEBHOOK_SECRET:
            webhook_logger.warning("Webhook request with invalid secret rejected.")
            raise HTTPException(status_code=401, detail="Invalid webhook secret.")

    # Handle both single lead (dict) and batch (list)
    leads: list[dict] = []
    if isinstance(payload, list):
        leads = payload
    elif isinstance(payload, dict):
        # Could be a single lead or wrapped response
        if "UNIQUE_QUERY_ID" in payload:
            leads = [payload]
        elif "data" in payload and isinstance(payload["data"], list):
            leads = payload["data"]
        else:
            # Treat the whole dict as a lead attempt
            leads = [payload]
    else:
        raise HTTPException(status_code=400, detail="Unexpected payload format.")

    saved_count = 0
    for lead_data in leads:
        # Basic validation: must have a query ID
        query_id = lead_data.get("UNIQUE_QUERY_ID") or lead_data.get("unique_query_id")
        if not query_id:
            webhook_logger.warning("Skipping lead without UNIQUE_QUERY_ID: %s", lead_data)
            continue
        inserted = await save_lead(lead_data)
        if inserted:
            saved_count += 1

    webhook_logger.info(
        "Webhook processed: %d leads received, %d new saved.",
        len(leads), saved_count,
    )

    return JSONResponse(
        status_code=200,
        content={"status": "ok", "received": len(leads), "saved": saved_count},
    )


@app.get("/health")
async def health_check() -> JSONResponse:
    """Health check endpoint. Returns status and total leads count."""
    try:
        count = await get_leads_count()
        return JSONResponse(
            content={"status": "healthy", "leads_count": count}
        )
    except Exception as e:
        webhook_logger.error("Health check failed: %s", e)
        return JSONResponse(
            status_code=500,
            content={"status": "unhealthy", "error": str(e)},
        )


@app.get("/leads")
async def list_leads() -> JSONResponse:
    """Return the last 20 leads from the database as JSON."""
    try:
        leads = await get_all_leads(limit=20)
        return JSONResponse(content={"leads": leads, "count": len(leads)})
    except Exception as e:
        webhook_logger.error("Failed to fetch leads: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────────────────────
# NEW REST API endpoints for frontend dashboard
# ──────────────────────────────────────────────────────────────


@app.get("/api/leads/export")
async def export_leads_csv(
    city: Optional[str] = Query(None, description="Filter by city"),
    product: Optional[str] = Query(None, description="Filter by product"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD HH:MM:SS)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD HH:MM:SS)"),
    search: Optional[str] = Query(None, description="Keyword search in name/product/message"),
) -> StreamingResponse:
    """Export filtered leads as a CSV download."""
    try:
        leads = await get_filtered_leads_all(
            city=city, product=product,
            start_date=start_date, end_date=end_date,
            search=search,
        )

        if not leads:
            raise HTTPException(status_code=404, detail="No leads match the given filters.")

        # Build CSV in memory
        output = io.StringIO()
        fieldnames = [
            "unique_query_id", "query_type", "query_time", "sender_name",
            "sender_mobile", "sender_email", "subject", "sender_company",
            "sender_address", "sender_city", "sender_state", "sender_pincode",
            "sender_country", "query_product_name", "query_message",
            "call_duration", "receiver_mobile", "created_at",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for lead in leads:
            writer.writerow(lead)

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=leads_export.csv"},
        )
    except HTTPException:
        raise
    except Exception as e:
        webhook_logger.error("Failed to export leads CSV: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/leads/{query_id}")
async def get_single_lead(query_id: str) -> JSONResponse:
    """Get a single lead by its unique_query_id.

    Args:
        query_id: The unique query ID of the lead.
    """
    try:
        lead = await get_lead_by_query_id(query_id)
        if not lead:
            raise HTTPException(status_code=404, detail=f"Lead with query_id '{query_id}' not found.")
        return JSONResponse(content={"lead": lead})
    except HTTPException:
        raise
    except Exception as e:
        webhook_logger.error("Failed to fetch lead %s: %s", query_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/leads")
async def get_leads_api(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    city: Optional[str] = Query(None, description="Filter by city"),
    product: Optional[str] = Query(None, description="Filter by product"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD HH:MM:SS)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD HH:MM:SS)"),
    search: Optional[str] = Query(None, description="Keyword search in name/product/message"),
) -> JSONResponse:
    """Return paginated leads with optional filters.

    Supports filtering by city, product, date range, and keyword search.
    """
    try:
        leads, total = await get_leads_paginated(
            page=page, per_page=per_page,
            city=city, product=product,
            start_date=start_date, end_date=end_date,
            search=search,
        )
        total_pages = math.ceil(total / per_page) if total > 0 else 0
        return JSONResponse(content={
            "leads": leads,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        })
    except Exception as e:
        webhook_logger.error("Failed to fetch paginated leads: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats")
async def get_stats() -> JSONResponse:
    """Return dashboard statistics.

    Includes total counts, time-based breakdowns, top cities/products,
    daily counts for the last 30 days, and query type breakdown.
    """
    try:
        stats = await get_dashboard_stats()
        return JSONResponse(content=stats)
    except Exception as e:
        webhook_logger.error("Failed to compute stats: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sync")
async def trigger_sync() -> JSONResponse:
    """Trigger a manual sync of the latest leads from IndiaMART API."""
    try:
        from tools.leads import sync_latest_leads
        result = await sync_latest_leads()
        return JSONResponse(content={"status": "ok", "message": result})
    except ImportError:
        webhook_logger.error("sync_latest_leads not available — tools.leads module missing.")
        raise HTTPException(status_code=500, detail="Sync function not available.")
    except Exception as e:
        webhook_logger.error("Sync failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/cities")
async def list_cities() -> JSONResponse:
    """Return list of unique cities with lead counts."""
    try:
        cities = await get_unique_cities()
        return JSONResponse(content={"cities": cities, "total": len(cities)})
    except Exception as e:
        webhook_logger.error("Failed to fetch cities: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/products")
async def list_products() -> JSONResponse:
    """Return list of unique products with lead counts."""
    try:
        products = await get_unique_products()
        return JSONResponse(content={"products": products, "total": len(products)})
    except Exception as e:
        webhook_logger.error("Failed to fetch products: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────────────────────
# Static files mount (for frontend) — must be LAST
# ──────────────────────────────────────────────────────────────

import os
_static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(_static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=_static_dir), name="static")


if __name__ == "__main__":
    import uvicorn

    asyncio.run(init_db())
    uvicorn.run(app, host="0.0.0.0", port=PORT)
