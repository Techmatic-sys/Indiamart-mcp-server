"""
SQLite database module for IndiaMART MCP Server.
Handles all database operations using aiosqlite for async access.
"""

import os
import aiosqlite
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

DB_PATH: str = os.getenv("DB_PATH", str(Path(__file__).parent.parent / "leads.db"))

logger = logging.getLogger("indiamart-mcp.db")

# SQL to create the leads table
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unique_query_id TEXT UNIQUE NOT NULL,
    query_type TEXT,
    query_time TEXT,
    sender_name TEXT,
    sender_mobile TEXT,
    sender_email TEXT,
    subject TEXT,
    sender_company TEXT,
    sender_address TEXT,
    sender_city TEXT,
    sender_state TEXT,
    sender_pincode TEXT,
    sender_country TEXT,
    query_product_name TEXT,
    query_message TEXT,
    call_duration TEXT,
    receiver_mobile TEXT,
    stage TEXT DEFAULT 'new',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_NOTES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS lead_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id TEXT NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (query_id) REFERENCES leads(unique_query_id)
);
"""

# Indexes for faster queries
CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_query_time ON leads (query_time);",
    "CREATE INDEX IF NOT EXISTS idx_sender_city ON leads (sender_city);",
    "CREATE INDEX IF NOT EXISTS idx_query_product_name ON leads (query_product_name);",
    "CREATE INDEX IF NOT EXISTS idx_lead_notes_query_id ON lead_notes (query_id);",
]


async def _get_db() -> aiosqlite.Connection:
    """Get a database connection with row_factory enabled."""
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


async def init_db() -> None:
    """Initialize the database: create tables and indexes if they don't exist."""
    logger.info("Initializing database at %s", DB_PATH)
    db = await _get_db()
    try:
        await db.execute(CREATE_TABLE_SQL)
        await db.execute(CREATE_NOTES_TABLE_SQL)
        # Add stage column to existing tables that don't have it
        try:
            await db.execute("ALTER TABLE leads ADD COLUMN stage TEXT DEFAULT 'new'")
        except Exception:
            pass  # Column already exists
        for idx_sql in CREATE_INDEXES_SQL:
            await db.execute(idx_sql)
        await db.commit()
        logger.info("Database initialized successfully.")
    finally:
        await db.close()


def _map_lead(raw: dict[str, Any]) -> dict[str, Any]:
    """Map an IndiaMART API response lead dict to our DB column names."""
    return {
        "unique_query_id": str(raw.get("UNIQUE_QUERY_ID", raw.get("unique_query_id", ""))),
        "query_type": str(raw.get("QUERY_TYPE", raw.get("query_type", ""))),
        "query_time": str(raw.get("QUERY_TIME", raw.get("query_time", ""))),
        "sender_name": str(raw.get("SENDER_NAME", raw.get("sender_name", ""))),
        "sender_mobile": str(raw.get("SENDER_MOBILE", raw.get("sender_mobile", ""))),
        "sender_email": str(raw.get("SENDER_EMAIL", raw.get("sender_email", ""))),
        "subject": str(raw.get("SUBJECT", raw.get("subject", ""))),
        "sender_company": str(raw.get("SENDER_COMPANY", raw.get("sender_company", ""))),
        "sender_address": str(raw.get("SENDER_ADDRESS", raw.get("sender_address", ""))),
        "sender_city": str(raw.get("SENDER_CITY", raw.get("sender_city", ""))),
        "sender_state": str(raw.get("SENDER_STATE", raw.get("sender_state", ""))),
        "sender_pincode": str(raw.get("SENDER_PINCODE", raw.get("sender_pincode", ""))),
        "sender_country": str(raw.get("SENDER_COUNTRY_ISO", raw.get("sender_country", ""))),
        "query_product_name": str(raw.get("QUERY_PRODUCT_NAME", raw.get("query_product_name", ""))),
        "query_message": str(raw.get("QUERY_MESSAGE", raw.get("query_message", ""))),
        "call_duration": str(raw.get("CALL_DURATION", raw.get("call_duration", ""))),
        "receiver_mobile": str(raw.get("RECEIVER_MOBILE", raw.get("receiver_mobile", ""))),
    }


async def save_lead(lead_raw: dict[str, Any]) -> bool:
    """Save a single lead to the database. Skips duplicates silently."""
    lead = _map_lead(lead_raw)
    db = await _get_db()
    try:
        await db.execute(
            """
            INSERT OR IGNORE INTO leads
                (unique_query_id, query_type, query_time, sender_name,
                 sender_mobile, sender_email, subject, sender_company,
                 sender_address, sender_city, sender_state, sender_pincode,
                 sender_country, query_product_name, query_message,
                 call_duration, receiver_mobile)
            VALUES
                (:unique_query_id, :query_type, :query_time, :sender_name,
                 :sender_mobile, :sender_email, :subject, :sender_company,
                 :sender_address, :sender_city, :sender_state, :sender_pincode,
                 :sender_country, :query_product_name, :query_message,
                 :call_duration, :receiver_mobile)
            """,
            lead,
        )
        await db.commit()
        changed = db.total_changes
        return changed > 0
    finally:
        await db.close()


async def save_leads(leads_raw: list[dict[str, Any]]) -> int:
    """Save multiple leads in a single transaction."""
    if not leads_raw:
        return 0
    mapped = [_map_lead(lead) for lead in leads_raw]
    db = await _get_db()
    inserted = 0
    try:
        for lead in mapped:
            cursor = await db.execute(
                """
                INSERT OR IGNORE INTO leads
                    (unique_query_id, query_type, query_time, sender_name,
                     sender_mobile, sender_email, subject, sender_company,
                     sender_address, sender_city, sender_state, sender_pincode,
                     sender_country, query_product_name, query_message,
                     call_duration, receiver_mobile)
                VALUES
                    (:unique_query_id, :query_type, :query_time, :sender_name,
                     :sender_mobile, :sender_email, :subject, :sender_company,
                     :sender_address, :sender_city, :sender_state, :sender_pincode,
                     :sender_country, :query_product_name, :query_message,
                     :call_duration, :receiver_mobile)
                """,
                lead,
            )
            if cursor.rowcount and cursor.rowcount > 0:
                inserted += 1
        await db.commit()
        logger.info("Saved %d new leads out of %d received.", inserted, len(leads_raw))
        return inserted
    finally:
        await db.close()


async def get_all_leads(limit: int = 20) -> list[dict[str, Any]]:
    """Fetch the most recent leads from the database."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM leads ORDER BY query_time DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_recent_leads_db(hours: int = 24) -> list[dict[str, Any]]:
    """Fetch leads from the last N hours from the local database."""
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM leads WHERE created_at >= ? ORDER BY query_time DESC",
            (cutoff,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def search_leads_db(keyword: str) -> list[dict[str, Any]]:
    """Search leads by keyword in product name or message."""
    pattern = f"%{keyword}%"
    db = await _get_db()
    try:
        cursor = await db.execute(
            """
            SELECT * FROM leads
            WHERE query_product_name LIKE ? OR query_message LIKE ?
            ORDER BY query_time DESC
            LIMIT 50
            """,
            (pattern, pattern),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_lead_by_query_id(query_id: str) -> dict[str, Any] | None:
    """Fetch a single lead by its unique query ID."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM leads WHERE unique_query_id = ?", (query_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_leads_by_date_range(start_date: str, end_date: str) -> list[dict[str, Any]]:
    """Fetch leads within a date range from the local database."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            """
            SELECT * FROM leads
            WHERE query_time >= ? AND query_time <= ?
            ORDER BY query_time DESC
            """,
            (start_date, end_date),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_lead_stats_db() -> dict[str, Any]:
    """Compute lead statistics from the local database."""
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM leads")
        row = await cursor.fetchone()
        total = row["cnt"] if row else 0

        cursor = await db.execute(
            """
            SELECT sender_city, COUNT(*) as cnt FROM leads
            WHERE sender_city != ''
            GROUP BY sender_city ORDER BY cnt DESC LIMIT 10
            """
        )
        by_city = {r["sender_city"]: r["cnt"] for r in await cursor.fetchall()}

        cursor = await db.execute(
            """
            SELECT query_product_name, COUNT(*) as cnt FROM leads
            WHERE query_product_name != ''
            GROUP BY query_product_name ORDER BY cnt DESC LIMIT 10
            """
        )
        by_product = {r["query_product_name"]: r["cnt"] for r in await cursor.fetchall()}

        seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        cursor = await db.execute(
            """
            SELECT DATE(query_time) as lead_date, COUNT(*) as cnt FROM leads
            WHERE DATE(query_time) >= ?
            GROUP BY lead_date ORDER BY lead_date DESC
            """,
            (seven_days_ago,),
        )
        by_date = {r["lead_date"]: r["cnt"] for r in await cursor.fetchall()}

        return {
            "total_leads": total,
            "leads_by_city": by_city,
            "leads_by_product": by_product,
            "leads_by_date_last_7_days": by_date,
        }
    finally:
        await db.close()


async def get_leads_count() -> int:
    """Return total number of leads in the database."""
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM leads")
        row = await cursor.fetchone()
        return row["cnt"] if row else 0
    finally:
        await db.close()


async def update_lead_stage(query_id: str, stage: str) -> bool:
    """Update the pipeline stage of a lead. Returns True if updated."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            "UPDATE leads SET stage = ? WHERE unique_query_id = ?",
            (stage.lower(), query_id),
        )
        await db.commit()
        return cursor.rowcount > 0 if cursor.rowcount else False
    finally:
        await db.close()


async def add_lead_note(query_id: str, note: str) -> int:
    """Add a note to a lead. Returns the note ID."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO lead_notes (query_id, note) VALUES (?, ?)",
            (query_id, note),
        )
        await db.commit()
        return cursor.lastrowid or 0
    finally:
        await db.close()


async def get_lead_notes(query_id: str) -> list[dict[str, Any]]:
    """Get all notes for a lead."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM lead_notes WHERE query_id = ? ORDER BY created_at DESC",
            (query_id,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()
