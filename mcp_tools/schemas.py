"""
Input validation schemas and structured response types for IndiaMART MCP tools.

Pydantic models handle input validation; dataclasses provide structured responses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, field_validator, Field


# ---------------------------------------------------------------------------
# Pydantic Input Validation (FIX-08)
# ---------------------------------------------------------------------------


def _parse_date(v: str) -> str:
    """Accept YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY, DD-Mon-YYYY — always return YYYY-MM-DD."""
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(v.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"Unrecognised date format: '{v}'. Use YYYY-MM-DD.")


class DateRangeInput(BaseModel):
    """Validates date range inputs for lead queries."""

    start_date: str
    end_date: str

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def validate_date(cls, v):
        return _parse_date(v)

    @field_validator("end_date")
    @classmethod
    def end_after_start(cls, v, info):
        if "start_date" in info.data and v < info.data["start_date"]:
            raise ValueError("end_date must be on or after start_date")
        return v


class RecentLeadsInput(BaseModel):
    """Validates hours parameter for recent leads queries."""

    hours: int = Field(
        default=24, ge=1, le=720, description="Hours to look back (1-720)"
    )


class SearchInput(BaseModel):
    """Validates keyword search input."""

    keyword: str = Field(
        min_length=2, max_length=100, description="Search term (min 2 chars)"
    )


class LeadIdInput(BaseModel):
    """Validates lead ID input."""

    query_id: str = Field(
        min_length=5, max_length=50, description="UNIQUE_QUERY_ID of the lead"
    )

    @field_validator("query_id")
    @classmethod
    def no_spaces(cls, v):
        v = v.strip()
        if " " in v:
            raise ValueError("query_id must not contain spaces")
        return v


class DraftReplyInput(BaseModel):
    """Validates draft reply inputs."""

    query_id: str = Field(min_length=5, max_length=50)
    seller_name: str = Field(min_length=2, max_length=100)
    product_info: str = Field(min_length=5, max_length=500)


# ---------------------------------------------------------------------------
# Structured Response Types (existing dataclasses)
# ---------------------------------------------------------------------------


@dataclass
class LeadSummary:
    """Compact lead representation for list views."""

    unique_query_id: str
    sender_name: str
    query_product_name: str
    sender_city: str
    query_time: str
    sender_mobile: str = ""
    sender_email: str = ""


@dataclass
class LeadDetail:
    """Full lead detail for single-lead views."""

    unique_query_id: str
    sender_name: str
    sender_company: str
    sender_mobile: str
    sender_email: str
    sender_city: str
    sender_state: str
    sender_pincode: str
    sender_country: str
    sender_address: str
    query_product_name: str
    subject: str
    query_message: str
    query_type: str
    query_time: str
    call_duration: str
    receiver_mobile: str
    created_at: str = ""


@dataclass
class StatsResult:
    """Lead statistics summary."""

    total_leads: int = 0
    leads_by_city: dict[str, int] = field(default_factory=dict)
    leads_by_product: dict[str, int] = field(default_factory=dict)
    leads_by_date: dict[str, int] = field(default_factory=dict)


@dataclass
class SyncResult:
    """Result of a lead sync operation."""

    fetched: int = 0
    new: int = 0
    duplicates: int = 0
    success: bool = True
    error: str = ""
