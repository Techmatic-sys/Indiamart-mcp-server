"""
MCP Tool definitions for IndiaMART Lead Manager.

All 10 tools with full business logic, Pydantic validation,
retry-resilient API calls, and consistent error contracts.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from mcp_tools.database import (
    init_db,
    save_leads,
    get_leads_by_date_range,
    get_lead_by_query_id,
    search_leads_db,
    get_recent_leads_db,
    get_lead_stats_db,
    update_lead_stage as db_update_lead_stage,
    add_lead_note as db_add_lead_note,
    get_lead_notes,
)
from mcp_tools.http_client import (
    fetch_leads_from_api,
    tool_error,
    tool_success,
    API_DATE_FMT,
    INDIAMART_API_KEY,
)
from mcp_tools.schemas import (
    DateRangeInput,
    RecentLeadsInput,
    SearchInput,
    LeadIdInput,
    DraftReplyInput,
)

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("indiamart-mcp.tools")

_initialized = False


async def _ensure_init() -> None:
    """Lazily initialize the database and validate config on first tool call."""
    global _initialized
    if not _initialized:
        if not INDIAMART_API_KEY:
            logger.warning(
                "INDIAMART_API_KEY not set — some tools may not work."
            )
        await init_db()
        _initialized = True


def _parse_user_date(date_str: str) -> datetime:
    """Parse a user-provided date string into a datetime.

    Supports: YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY, DD-Mon-YYYY.
    """
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    raise ValueError(
        f"Cannot parse date '{date_str}'. Use YYYY-MM-DD or DD-MM-YYYY format."
    )


def register_all_tools(mcp: FastMCP) -> None:
    """Register all 10 MCP tools on the given FastMCP server instance."""

    # ─── Tool 1: Get Leads by Date Range ────────────────────────────────

    @mcp.tool()
    async def tool_get_leads_by_date(start_date: str, end_date: str) -> str:
        """Fetch and store IndiaMART buyer enquiries for a specific date range.

        Queries the IndiaMART CRM API and saves results to local SQLite DB.
        Returns a formatted list of all leads found in the period.

        Args:
            start_date: Start date. Accepts YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY.
                Example: "2026-03-01" or "01-03-2026"
            end_date: End date (inclusive). Must be >= start_date.
                Example: "2026-03-25"

        Returns:
            A formatted list of leads with: buyer name, company, city,
            product enquired, message, phone, and email.

        Example usage:
            "Show me all leads from this week"
            "Get leads between March 1 and March 25"
            "Fetch January 2026 leads"
        """
        await _ensure_init()
        try:
            DateRangeInput(start_date=start_date, end_date=end_date)
        except Exception as e:
            return tool_error("Invalid date input", str(e))

        try:
            start_dt = _parse_user_date(start_date)
            end_dt = _parse_user_date(end_date)
        except ValueError as e:
            return tool_error("Date parse error", str(e))

        start_api = start_dt.strftime(API_DATE_FMT)
        end_api = end_dt.replace(hour=23, minute=59, second=59).strftime(API_DATE_FMT)

        try:
            leads = await fetch_leads_from_api(start_api, end_api)
        except RuntimeError as e:
            return tool_error("API fetch failed", str(e))

        if not leads:
            return f"No leads found between {start_date} and {end_date}."

        new_count = await save_leads(leads)

        lines = [
            f"📊 **Leads Report: {start_date} → {end_date}**",
            f"Total leads fetched: {len(leads)} ({new_count} new, {len(leads) - new_count} already in DB)",
            "",
            "| # | Name | Product | City | Time |",
            "|---|------|---------|------|------|",
        ]
        for i, lead in enumerate(leads[:30], 1):
            name = lead.get("SENDER_NAME", "N/A")
            product = lead.get("QUERY_PRODUCT_NAME", "N/A")
            city = lead.get("SENDER_CITY", "N/A")
            time = lead.get("QUERY_TIME", "N/A")
            lines.append(f"| {i} | {name} | {product} | {city} | {time} |")

        if len(leads) > 30:
            lines.append(f"\n... and {len(leads) - 30} more leads.")

        return "\n".join(lines)

    # ─── Tool 2: Get Recent Leads ───────────────────────────────────────

    @mcp.tool()
    async def tool_get_recent_leads(hours: int = 24) -> str:
        """Get leads from the last N hours. Syncs from IndiaMART first, then shows results.

        Automatically pulls the latest leads from IndiaMART's API and saves
        them to the local database before returning results.

        Args:
            hours: Number of hours to look back (1-720, default: 24).
                Example: 24 for last day, 168 for last week.

        Returns:
            Formatted list of recent leads with contact details and messages.

        Example usage:
            "Show me leads from the last 24 hours"
            "Any new enquiries today?"
            "Get leads from the past week"
        """
        await _ensure_init()
        try:
            validated = RecentLeadsInput(hours=hours)
        except Exception as e:
            return tool_error("Invalid hours value", str(e))

        now = datetime.now()
        start_dt = now - timedelta(hours=validated.hours)
        start_api = start_dt.strftime(API_DATE_FMT)
        end_api = now.strftime(API_DATE_FMT)

        try:
            api_leads = await fetch_leads_from_api(start_api, end_api)
            if api_leads:
                await save_leads(api_leads)
        except RuntimeError as e:
            logger.warning("Could not sync from API, using local DB: %s", e)

        leads = await get_recent_leads_db(validated.hours)

        if not leads:
            return f"No leads found in the last {validated.hours} hours."

        lines = [
            f"📬 **Recent Leads (last {validated.hours} hours)** — {len(leads)} total",
            "",
        ]
        for i, lead in enumerate(leads, 1):
            lines.append(
                f"{i}. **{lead['sender_name']}** — {lead['query_product_name']}\n"
                f"   📱 {lead['sender_mobile']} | 📧 {lead['sender_email']}\n"
                f"   🏙️ {lead['sender_city']} | 🕐 {lead['query_time']}\n"
                f"   💬 {lead['query_message'][:100]}{'...' if len(lead.get('query_message', '')) > 100 else ''}\n"
            )

        return "\n".join(lines)

    # ─── Tool 3: Search Leads ───────────────────────────────────────────

    @mcp.tool()
    async def tool_search_leads(keyword: str) -> str:
        """Search locally stored leads by keyword in product name or message.

        Searches the local SQLite database for leads matching the keyword.
        Useful for finding specific product enquiries or buyer messages.

        Args:
            keyword: Search term (min 2 characters, max 100).
                Example: "steel pipes", "construction", "Mumbai"

        Returns:
            Formatted list of matching leads with contact info and messages.

        Example usage:
            "Search for leads about steel pipes"
            "Find enquiries mentioning construction"
            "Any leads asking about copper?"
        """
        await _ensure_init()
        try:
            validated = SearchInput(keyword=keyword)
        except Exception as e:
            return tool_error("Invalid search input", str(e))

        leads = await search_leads_db(validated.keyword)

        if not leads:
            return f"No leads found matching '{validated.keyword}'."

        lines = [
            f"🔍 **Search Results for '{validated.keyword}'** — {len(leads)} matches",
            "",
        ]
        for i, lead in enumerate(leads, 1):
            lines.append(
                f"{i}. [{lead['unique_query_id']}] **{lead['sender_name']}** — {lead['query_product_name']}\n"
                f"   📱 {lead['sender_mobile']} | 🏙️ {lead['sender_city']} | 🕐 {lead['query_time']}\n"
                f"   💬 {lead['query_message'][:120]}{'...' if len(lead.get('query_message', '')) > 120 else ''}\n"
            )

        return "\n".join(lines)

    # ─── Tool 4: Get Lead by ID ─────────────────────────────────────────

    @mcp.tool()
    async def tool_get_lead_by_id(query_id: str) -> str:
        """Get full details of a specific lead by its unique query ID.

        Returns comprehensive information about a single lead including
        all contact details, product enquiry, and message content.

        Args:
            query_id: The UNIQUE_QUERY_ID of the lead (no spaces).
                Example: "IML1234567890"

        Returns:
            Complete lead details including name, company, contact info,
            product enquiry, message, and timestamps.

        Example usage:
            "Show me details for lead IML1234567890"
            "Get the full info on query TEST123456789"
        """
        await _ensure_init()
        try:
            validated = LeadIdInput(query_id=query_id)
        except Exception as e:
            return tool_error("Invalid lead ID", str(e))

        lead = await get_lead_by_query_id(validated.query_id)

        if not lead:
            return tool_error(
                f"No lead found with ID '{validated.query_id}'",
                "Make sure you've synced your leads first.",
            )

        lines = [
            f"📋 **Lead Details — {lead['unique_query_id']}**",
            "",
            f"**Name:** {lead['sender_name']}",
            f"**Company:** {lead['sender_company']}",
            f"**Mobile:** {lead['sender_mobile']}",
            f"**Email:** {lead['sender_email']}",
            f"**City:** {lead['sender_city']}, {lead['sender_state']}",
            f"**Pincode:** {lead['sender_pincode']}",
            f"**Country:** {lead['sender_country']}",
            f"**Address:** {lead['sender_address']}",
            "",
            f"**Product:** {lead['query_product_name']}",
            f"**Subject:** {lead['subject']}",
            f"**Message:** {lead['query_message']}",
            f"**Query Type:** {lead['query_type']}",
            f"**Query Time:** {lead['query_time']}",
            f"**Call Duration:** {lead['call_duration']}",
            f"**Receiver Mobile:** {lead['receiver_mobile']}",
            f"**Stage:** {lead.get('stage', 'new')}",
            f"**Saved At:** {lead['created_at']}",
        ]

        return "\n".join(lines)

    # ─── Tool 5: Export Leads CSV ───────────────────────────────────────

    @mcp.tool()
    async def tool_export_leads_csv(start_date: str, end_date: str) -> str:
        """Export leads from the local database as CSV for a given date range.

        Generates a CSV-formatted string of leads for import into
        spreadsheets, CRMs, or other analysis tools.

        Args:
            start_date: Start date. Accepts YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY.
                Example: "2026-03-01"
            end_date: End date (inclusive). Must be >= start_date.
                Example: "2026-03-25"

        Returns:
            CSV-formatted string with lead data ready for download.

        Example usage:
            "Export all leads from March as CSV"
            "Give me a CSV of last week's leads"
        """
        await _ensure_init()
        try:
            DateRangeInput(start_date=start_date, end_date=end_date)
        except Exception as e:
            return tool_error("Invalid date input", str(e))

        try:
            start_dt = _parse_user_date(start_date)
            end_dt = _parse_user_date(end_date)
        except ValueError as e:
            return tool_error("Date parse error", str(e))

        leads = await get_leads_by_date_range(
            start_dt.strftime("%Y-%m-%d 00:00:00"),
            end_dt.strftime("%Y-%m-%d 23:59:59"),
        )

        if not leads:
            return f"No leads found in the database between {start_date} and {end_date}. Try syncing your leads first by asking to sync latest leads from IndiaMART."

        output = io.StringIO()
        fieldnames = [
            "unique_query_id", "query_time", "sender_name", "sender_mobile",
            "sender_email", "sender_company", "sender_city", "sender_state",
            "query_product_name", "query_message", "query_type", "subject",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for lead in leads:
            writer.writerow(lead)

        csv_str = output.getvalue()
        return f"📄 **CSV Export ({len(leads)} leads, {start_date} → {end_date})**\n\n```csv\n{csv_str}```"

    # ─── Tool 6: Sync Latest Leads ─────────────────────────────────────

    @mcp.tool()
    async def tool_sync_latest_leads() -> str:
        """Sync the latest leads from IndiaMART into the local database.

        Pulls the last 7 days of leads from the IndiaMART CRM API and
        saves any new ones to the local SQLite database. Duplicates are
        automatically skipped.

        Returns:
            Summary showing how many leads were fetched, how many were new,
            and how many were duplicates.

        Example usage:
            "Sync my latest leads"
            "Pull new leads from IndiaMART"
            "Update my lead database"
        """
        await _ensure_init()
        now = datetime.now()
        start_dt = now - timedelta(days=7)
        start_api = start_dt.strftime(API_DATE_FMT)
        end_api = now.strftime(API_DATE_FMT)

        try:
            leads = await fetch_leads_from_api(start_api, end_api)
        except RuntimeError as e:
            return tool_error("Sync failed", str(e))

        if not leads:
            return tool_success("Sync complete. No new leads from IndiaMART in the last 7 days.")

        new_count = await save_leads(leads)
        return tool_success(
            "Sync Complete",
            f"Fetched: {len(leads)} leads from IndiaMART\n"
            f"New: {new_count} leads saved to database\n"
            f"Duplicates skipped: {len(leads) - new_count}",
        )

    # ─── Tool 7: Get Lead Stats ────────────────────────────────────────

    @mcp.tool()
    async def tool_get_lead_stats() -> str:
        """Get lead analytics — total count, top cities, top products, and daily trends.

        Computes comprehensive statistics from the local lead database
        including geographic distribution, product demand, and volume trends.

        Returns:
            Formatted statistics with total leads, top 10 cities,
            top 10 products, and daily counts for the last 7 days.

        Example usage:
            "Show me my lead statistics"
            "Which cities are sending the most enquiries?"
            "What are my top products by lead count?"
        """
        await _ensure_init()
        stats = await get_lead_stats_db()

        total = stats["total_leads"]
        if total == 0:
            return (
                "📊 **Lead Statistics**\n\n"
                "No leads in the database yet. Please sync your latest leads "
                "from IndiaMART first."
            )

        lines = [
            "📊 **Lead Statistics**",
            "",
            f"**Total Leads in Database:** {total}",
            "",
        ]

        by_city = stats.get("leads_by_city", {})
        if by_city:
            lines.append("**🏙️ Top Cities:**")
            for city, count in by_city.items():
                bar = "█" * min(count, 20)
                lines.append(f"  {city}: {count} {bar}")
            lines.append("")

        by_product = stats.get("leads_by_product", {})
        if by_product:
            lines.append("**📦 Top Products:**")
            for product, count in by_product.items():
                bar = "█" * min(count, 20)
                lines.append(f"  {product}: {count} {bar}")
            lines.append("")

        by_date = stats.get("leads_by_date_last_7_days", {})
        if by_date:
            lines.append("**📅 Last 7 Days:**")
            for date, count in by_date.items():
                bar = "█" * min(count, 20)
                lines.append(f"  {date}: {count} {bar}")
            lines.append("")

        return "\n".join(lines)

    # ─── Tool 8: Draft Reply ───────────────────────────────────────────

    @mcp.tool()
    async def tool_draft_reply(query_id: str, seller_name: str, product_info: str) -> str:
        """Draft a professional reply for a buyer enquiry.

        Fetches the lead from the database and composes a personalized,
        professional reply message ready to send via IndiaMART, email,
        or WhatsApp.

        Args:
            query_id: The UNIQUE_QUERY_ID of the lead to reply to.
                Example: "IML1234567890"
            seller_name: Your name or business name.
                Example: "Vasanth Industries"
            product_info: Product details, pricing, or availability to include.
                Example: "We offer SS304 pipes at ₹250/kg with free delivery for orders above 500kg."

        Returns:
            A professional plain-text reply message with lead context.

        Example usage:
            "Draft a reply to lead IML123 from Vasanth Industries about steel pipes at ₹250/kg"
        """
        await _ensure_init()
        try:
            validated = DraftReplyInput(
                query_id=query_id,
                seller_name=seller_name,
                product_info=product_info,
            )
        except Exception as e:
            return tool_error("Invalid input", str(e))

        lead = await get_lead_by_query_id(validated.query_id)

        if not lead:
            return tool_error(
                f"No lead found with ID '{validated.query_id}'",
                "Please sync your leads first by asking to sync latest leads from IndiaMART.",
            )

        buyer_name = lead["sender_name"] or "Sir/Madam"
        product_name = lead["query_product_name"] or "your enquired product"
        buyer_message = lead["query_message"] or ""
        buyer_city = lead["sender_city"] or ""

        city_line = f" from {buyer_city}" if buyer_city else ""

        reply_lines = [
            f"Dear {buyer_name},",
            "",
            f"Thank you for your enquiry regarding **{product_name}**. "
            f"We appreciate your interest and are glad to connect with you{city_line}.",
            "",
        ]

        if buyer_message:
            reply_lines.extend([
                "We have reviewed your requirement:",
                f'> "{buyer_message[:300]}{"..." if len(buyer_message) > 300 else ""}"',
                "",
            ])

        reply_lines.extend([
            "Here are the details regarding your enquiry:",
            "",
            validated.product_info,
            "",
            "We would be happy to discuss your requirements in detail and provide you "
            "with a customized quotation. Please feel free to reach out to us for any "
            "further questions.",
            "",
            "Looking forward to your response.",
            "",
            "Warm regards,",
            validated.seller_name,
        ])

        reply_text = "\n".join(reply_lines)

        return (
            f"✉️ **Draft Reply for Lead {validated.query_id}**\n"
            f"**To:** {buyer_name} ({lead['sender_email']})\n"
            f"**Product:** {product_name}\n"
            f"**Query Type:** {lead['query_type']}\n\n"
            f"---\n\n"
            f"{reply_text}\n\n"
            f"---\n"
            f"💡 *You can copy this reply and send it via IndiaMART, email, or WhatsApp.*"
        )

    # ─── Tool 9: Update Lead Stage (NEW — Write Tool) ──────────────────

    @mcp.tool()
    async def tool_update_lead_stage(
        query_id: str, new_stage: str, note: str = ""
    ) -> str:
        """Update the pipeline stage of a lead in the local database.

        Moves a lead through your sales pipeline stages. Optionally attach
        a note explaining the stage change.

        Args:
            query_id: The UNIQUE_QUERY_ID of the lead.
                Example: "IML1234567890"
            new_stage: One of: new, contacted, qualified, proposal,
                negotiation, won, lost.
                Example: "qualified"
            note: Optional reason for stage change.
                Example: "Buyer confirmed budget of 5 lakhs"

        Returns:
            Confirmation of the stage update.

        Example usage:
            "Move lead IML123 to qualified stage"
            "Mark lead IML456 as won — deal closed at 10 lakhs"
        """
        await _ensure_init()

        valid_stages = {
            "new", "contacted", "qualified", "proposal",
            "negotiation", "won", "lost",
        }
        if new_stage.lower() not in valid_stages:
            return tool_error(
                f"Invalid stage '{new_stage}'",
                f"Valid stages: {', '.join(sorted(valid_stages))}",
            )

        # Verify lead exists
        lead = await get_lead_by_query_id(query_id.strip())
        if not lead:
            return tool_error(
                f"No lead found with ID '{query_id}'",
                "Please sync your leads first.",
            )

        updated = await db_update_lead_stage(query_id.strip(), new_stage.lower())
        if not updated:
            return tool_error("Failed to update stage", "Database update returned no changes.")

        # Add note if provided
        if note:
            await db_add_lead_note(
                query_id.strip(),
                f"[Stage → {new_stage.lower()}] {note}",
            )

        return tool_success(
            f"Lead {query_id} moved to '{new_stage.lower()}'",
            f"Previous stage: {lead.get('stage', 'new')}\n"
            + (f"Note: {note}" if note else ""),
        )

    # ─── Tool 10: Add Note (NEW — Write Tool) ──────────────────────────

    @mcp.tool()
    async def tool_add_note(query_id: str, note: str) -> str:
        """Add a private note to a lead for future reference.

        Attach notes to leads for tracking conversations, follow-ups,
        pricing discussions, or any other context you want to remember.

        Args:
            query_id: The UNIQUE_QUERY_ID of the lead.
                Example: "IML1234567890"
            note: The note text to attach (max 1000 characters).
                Example: "Called buyer — interested but waiting for Q2 budget"

        Returns:
            Confirmation that the note was added.

        Example usage:
            "Add a note to lead IML123: Called buyer, very interested in bulk order"
            "Note on IML456: Follow up next Monday about pricing"
        """
        await _ensure_init()

        if len(note) > 1000:
            return tool_error("Note too long", "Maximum 1000 characters allowed.")

        if len(note.strip()) < 2:
            return tool_error("Note too short", "Please provide a meaningful note.")

        # Verify lead exists
        lead = await get_lead_by_query_id(query_id.strip())
        if not lead:
            return tool_error(
                f"No lead found with ID '{query_id}'",
                "Please sync your leads first.",
            )

        note_id = await db_add_lead_note(query_id.strip(), note.strip())

        # Get all notes for context
        all_notes = await get_lead_notes(query_id.strip())

        return tool_success(
            f"Note added to lead {query_id}",
            f"Note #{note_id}: {note.strip()}\n"
            f"Total notes on this lead: {len(all_notes)}",
        )
