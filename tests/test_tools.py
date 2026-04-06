"""
Tests for IndiaMART MCP tools — validation, business logic, and integration.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch
from pydantic import ValidationError

from mcp_tools.database import save_leads, get_lead_by_query_id, update_lead_stage, add_lead_note, get_lead_notes
from mcp_tools.schemas import (
    DateRangeInput,
    RecentLeadsInput,
    SearchInput,
    LeadIdInput,
    DraftReplyInput,
)


# ─── Pydantic Validation Tests (FIX-08, FIX-11) ────────────────────────


class TestDateRangeValidation:
    """Tests for DateRangeInput schema."""

    def test_accepts_yyyy_mm_dd(self):
        d = DateRangeInput(start_date="2026-03-01", end_date="2026-03-25")
        assert d.start_date == "2026-03-01"
        assert d.end_date == "2026-03-25"

    def test_accepts_dd_mm_yyyy(self):
        d = DateRangeInput(start_date="01-03-2026", end_date="25-03-2026")
        assert d.start_date == "2026-03-01"
        assert d.end_date == "2026-03-25"

    def test_accepts_dd_slash_mm_yyyy(self):
        d = DateRangeInput(start_date="01/03/2026", end_date="25/03/2026")
        assert d.start_date == "2026-03-01"
        assert d.end_date == "2026-03-25"

    def test_rejects_wrong_order(self):
        with pytest.raises(ValidationError, match="end_date must be on or after"):
            DateRangeInput(start_date="2026-03-25", end_date="2026-03-01")

    def test_rejects_invalid_format(self):
        with pytest.raises(ValidationError, match="Unrecognised date format"):
            DateRangeInput(start_date="March 1st 2026", end_date="2026-03-25")


class TestRecentLeadsValidation:
    """Tests for RecentLeadsInput schema."""

    def test_default_24_hours(self):
        r = RecentLeadsInput()
        assert r.hours == 24

    def test_valid_hours(self):
        r = RecentLeadsInput(hours=168)
        assert r.hours == 168

    def test_rejects_zero(self):
        with pytest.raises(ValidationError):
            RecentLeadsInput(hours=0)

    def test_rejects_over_720(self):
        with pytest.raises(ValidationError):
            RecentLeadsInput(hours=721)


class TestSearchValidation:
    """Tests for SearchInput schema."""

    def test_valid_keyword(self):
        s = SearchInput(keyword="steel pipes")
        assert s.keyword == "steel pipes"

    def test_rejects_short_keyword(self):
        with pytest.raises(ValidationError):
            SearchInput(keyword="a")

    def test_rejects_empty(self):
        with pytest.raises(ValidationError):
            SearchInput(keyword="")


class TestLeadIdValidation:
    """Tests for LeadIdInput schema."""

    def test_valid_id(self):
        lead_id = LeadIdInput(query_id="TEST123456789")
        assert lead_id.query_id == "TEST123456789"

    def test_rejects_spaces(self):
        with pytest.raises(ValidationError, match="must not contain spaces"):
            LeadIdInput(query_id="IML 123 456")

    def test_strips_whitespace(self):
        lead_id = LeadIdInput(query_id="TEST123456789  ")
        assert lead_id.query_id == "TEST123456789"

    def test_rejects_too_short(self):
        with pytest.raises(ValidationError):
            LeadIdInput(query_id="ABC")


class TestDraftReplyValidation:
    """Tests for DraftReplyInput schema."""

    def test_valid_input(self):
        d = DraftReplyInput(
            query_id="TEST123456789",
            seller_name="Vasanth Industries",
            product_info="SS304 pipes at Rs 250/kg",
        )
        assert d.seller_name == "Vasanth Industries"

    def test_rejects_short_product_info(self):
        with pytest.raises(ValidationError):
            DraftReplyInput(
                query_id="TEST123456789",
                seller_name="Test",
                product_info="Hi",
            )


# ─── Tool-Level Integration Tests ──────────────────────────────────────


class MockMCP:
    """Minimal FastMCP stand-in that captures registered tool functions."""

    def __init__(self):
        self._tools: dict = {}

    def tool(self):
        def decorator(func):
            self._tools[func.__name__] = func
            return func
        return decorator


@pytest.fixture
def mcp_tools(setup_test_db):
    """Register all tools on a mock MCP and return the tool dict."""
    from mcp_tools.tools import register_all_tools
    mcp = MockMCP()
    register_all_tools(mcp)
    return mcp._tools


class TestToolLevel:
    """Call tool functions end-to-end with DB + mocked API."""

    async def test_tool_search_leads(self, mcp_tools, sample_leads):
        """tool_search_leads should find leads matching a keyword."""
        await save_leads(sample_leads)

        result = await mcp_tools["tool_search_leads"](keyword="steel")
        assert "Rahul Sharma" in result
        assert "steel" in result.lower()

    async def test_tool_draft_reply(self, mcp_tools, sample_leads):
        """tool_draft_reply should compose a personalised reply for a saved lead."""
        await save_leads(sample_leads)

        result = await mcp_tools["tool_draft_reply"](
            query_id="TEST123456789",
            seller_name="Vasanth Industries",
            product_info="SS304 pipes at Rs 250/kg, MOQ 100 units",
        )
        assert "Rahul Sharma" in result
        assert "Vasanth Industries" in result
        assert "Rs 250/kg" in result

    async def test_tool_sync_latest_leads(self, mcp_tools, sample_leads):
        """tool_sync_latest_leads should fetch from API and report new leads saved."""
        with patch("mcp_tools.tools.fetch_leads_from_api", new_callable=AsyncMock) as mock:
            mock.return_value = sample_leads
            result = await mcp_tools["tool_sync_latest_leads"]()
        assert "3" in result          # 3 leads fetched
        assert "new" in result.lower()


# ─── Database & Tool Integration Tests ─────────────────────────────────


class TestDatabaseOperations:
    """Tests for database CRUD operations."""

    async def test_save_and_retrieve_lead(self, sample_leads):
        count = await save_leads(sample_leads)
        assert count == 3

        lead = await get_lead_by_query_id("TEST123456789")
        assert lead is not None
        assert lead["sender_name"] == "Rahul Sharma"
        assert lead["sender_city"] == "Mumbai"

    async def test_update_lead_stage(self, sample_leads):
        await save_leads(sample_leads)
        updated = await update_lead_stage("TEST123456789", "qualified")
        assert updated is True

        lead = await get_lead_by_query_id("TEST123456789")
        assert lead["stage"] == "qualified"

    async def test_add_and_get_notes(self, sample_leads):
        await save_leads(sample_leads)
        note_id = await add_lead_note("TEST123456789", "Called buyer, very interested")
        assert note_id > 0

        notes = await get_lead_notes("TEST123456789")
        assert len(notes) == 1
        assert "very interested" in notes[0]["note"]

    async def test_duplicate_leads_skipped(self, sample_leads):
        count1 = await save_leads(sample_leads)
        count2 = await save_leads(sample_leads)
        assert count1 == 3
        assert count2 == 0  # All duplicates
