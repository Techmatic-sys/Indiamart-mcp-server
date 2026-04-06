"""
Pytest fixtures for IndiaMART MCP Server tests.
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

# Point DB to a temporary file for tests
_test_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_test_db.close()
os.environ["DB_PATH"] = _test_db.name
os.environ["INDIAMART_API_KEY"] = "test_api_key_12345"
os.environ["INDIAMART_GLID"] = "test_glid_12345"

import aiosqlite  # noqa: E402
from mcp_tools.database import init_db  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def setup_test_db():
    """Initialize a fresh test database before each test."""
    await init_db()
    # Wipe all data so each test starts with a clean slate
    async with aiosqlite.connect(_test_db.name) as db:
        await db.execute("DELETE FROM leads")
        await db.execute("DELETE FROM lead_notes")
        await db.commit()
    yield


@pytest.fixture
def sample_lead():
    """Return a sample lead dict as returned by the IndiaMART API."""
    return {
        "UNIQUE_QUERY_ID": "TEST123456789",
        "QUERY_TYPE": "W",
        "QUERY_TIME": "2026-03-25 10:30:00",
        "SENDER_NAME": "Rahul Sharma",
        "SENDER_MOBILE": "9876543210",
        "SENDER_EMAIL": "rahul@example.com",
        "SUBJECT": "Enquiry for Steel Pipes",
        "SENDER_COMPANY": "Sharma Industries",
        "SENDER_ADDRESS": "123 Industrial Area",
        "SENDER_CITY": "Mumbai",
        "SENDER_STATE": "Maharashtra",
        "SENDER_PINCODE": "400001",
        "SENDER_COUNTRY_ISO": "IN",
        "QUERY_PRODUCT_NAME": "Stainless Steel Pipes",
        "QUERY_MESSAGE": "I need 100 units of SS304 pipes, 2 inch diameter. Please share best price.",
        "CALL_DURATION": "",
        "RECEIVER_MOBILE": "9999888877",
    }


@pytest.fixture
def sample_leads(sample_lead):
    """Return a list of sample leads."""
    lead2 = sample_lead.copy()
    lead2["UNIQUE_QUERY_ID"] = "TEST987654321"
    lead2["SENDER_NAME"] = "Priya Patel"
    lead2["SENDER_CITY"] = "Ahmedabad"
    lead2["QUERY_PRODUCT_NAME"] = "GI Pipes"
    lead2["QUERY_MESSAGE"] = "Need GI pipes for construction project."

    lead3 = sample_lead.copy()
    lead3["UNIQUE_QUERY_ID"] = "TEST111222333"
    lead3["SENDER_NAME"] = "Vikram Singh"
    lead3["SENDER_CITY"] = "Delhi"
    lead3["QUERY_PRODUCT_NAME"] = "Copper Tubes"
    lead3["QUERY_MESSAGE"] = "Require copper tubes for AC installation."

    return [sample_lead, lead2, lead3]


@pytest.fixture
def mock_api_response(sample_leads):
    """Mock the IndiaMART API to return sample leads."""
    with patch(
        "mcp_tools.http_client.fetch_leads_from_api", new_callable=AsyncMock
    ) as mock:
        mock.return_value = sample_leads
        yield mock
