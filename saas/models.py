"""
SQLAlchemy ORM models for the LeadFlow CRM platform.

All models use UUID primary keys and include tenant-scoping via ``user_id``
foreign keys where applicable.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ─── Portable UUID type (works with both PostgreSQL and SQLite) ──────────────


class PortableUUID(TypeDecorator):
    """Platform-independent UUID type. Uses String(36) for SQLite, native UUID for PG."""
    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return str(value)
        return value

    def process_result_value(self, value, dialect):
        return value


# ─── Base ────────────────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


# ─── Enums (as DB-level CHECK constraints) ───────────────────────────────────

PlanEnum = String(20)
SubscriptionStatusEnum = String(20)
SyncTypeEnum = String(20)
SyncStatusEnum = String(20)
SentViaEnum = String(20)
ReplyStatusEnum = String(20)
LeadStageEnum = String(20)
ActivityTypeEnum = String(20)


# ─── User ────────────────────────────────────────────────────────────────────


class User(Base):
    """A tenant user with their IndiaMART credentials and subscription plan."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        PortableUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    indiamart_api_key: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Encrypted at the application layer"
    )
    indiamart_glid: Mapped[str | None] = mapped_column(String(50), nullable=True)
    plan: Mapped[str] = mapped_column(PlanEnum, nullable=False, default="free")
    plan_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    leads: Mapped[list["Lead"]] = relationship(
        back_populates="user", foreign_keys="[Lead.user_id]", cascade="all, delete-orphan"
    )
    assigned_leads: Mapped[list["Lead"]] = relationship(
        back_populates="assigned_user", foreign_keys="[Lead.assigned_to]"
    )
    subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    sync_logs: Mapped[list["SyncLog"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    auto_replies: Mapped[list["AutoReply"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    activities: Mapped[list["Activity"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    notifications: Mapped[list["Notification"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    reminders: Mapped[list["Reminder"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    email_templates: Mapped[list["EmailTemplate"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User {self.email} plan={self.plan}>"


# ─── Lead ────────────────────────────────────────────────────────────────────


class Lead(Base):
    """An IndiaMART buyer lead scoped to a user (tenant)."""

    __tablename__ = "leads"

    id: Mapped[str] = mapped_column(
        PortableUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        PortableUUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # IndiaMART fields
    unique_query_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    query_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    query_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_mobile: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sender_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    sender_company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    sender_city: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    sender_state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sender_pincode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    sender_country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    query_product_name: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    query_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    call_duration: Mapped[str | None] = mapped_column(String(20), nullable=True)
    receiver_mobile: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # App-specific fields
    ai_reply_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ai_reply_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    lead_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_starred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Pipeline / Kanban fields
    lead_stage: Mapped[str] = mapped_column(
        LeadStageEnum, nullable=False, default="new", index=True,
        comment="Pipeline stage: new, contacted, qualified, proposal, negotiation, won, lost"
    )
    deal_value: Mapped[float | None] = mapped_column(
        Float, nullable=True, default=None,
        comment="Estimated deal value in INR"
    )
    assigned_to: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True,
        comment="User this lead is assigned to (for multi-agent teams)"
    )
    response_time_mins: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="Time in minutes from lead creation to first response"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship(
        back_populates="leads", foreign_keys="[Lead.user_id]"
    )
    assigned_user: Mapped["User | None"] = relationship(
        back_populates="assigned_leads", foreign_keys="[Lead.assigned_to]"
    )
    auto_replies: Mapped[list["AutoReply"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan"
    )
    activities: Mapped[list["Activity"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan"
    )
    reminders: Mapped[list["Reminder"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan"
    )
    notifications: Mapped[list["Notification"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Lead {self.unique_query_id} stage={self.lead_stage} user={self.user_id}>"


# ─── Activity ────────────────────────────────────────────────────────────────


class Activity(Base):
    """Activity timeline entry for a lead (note, call, email, whatsapp, meeting)."""

    __tablename__ = "activities"

    id: Mapped[str] = mapped_column(
        PortableUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    lead_id: Mapped[str] = mapped_column(
        PortableUUID(), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        PortableUUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    activity_type: Mapped[str] = mapped_column(
        ActivityTypeEnum, nullable=False,
        comment="Type: note, call, email, whatsapp, meeting, stage_change"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    lead: Mapped["Lead"] = relationship(back_populates="activities")
    user: Mapped["User"] = relationship(back_populates="activities")

    def __repr__(self) -> str:
        return f"<Activity {self.activity_type} lead={self.lead_id}>"


# ─── Notification ────────────────────────────────────────────────────────────


class Notification(Base):
    """In-app notification for a user (new_lead, reminder_due, stage_change, deal_won)."""

    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(
        PortableUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        PortableUUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lead_id: Mapped[str | None] = mapped_column(
        PortableUUID(), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True
    )
    notification_type: Mapped[str] = mapped_column(
        String(30), nullable=False, index=True,
        comment="Type: new_lead, reminder_due, stage_change, deal_won"
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="notifications")
    lead: Mapped["Lead | None"] = relationship(back_populates="notifications")

    def __repr__(self) -> str:
        return f"<Notification {self.notification_type} read={self.is_read} user={self.user_id}>"


# ─── Reminder ────────────────────────────────────────────────────────────────


class Reminder(Base):
    """Follow-up reminder for a user, optionally tied to a lead."""

    __tablename__ = "reminders"

    id: Mapped[str] = mapped_column(
        PortableUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        PortableUUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lead_id: Mapped[str | None] = mapped_column(
        PortableUUID(), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True
    )
    remind_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="reminders")
    lead: Mapped["Lead | None"] = relationship(back_populates="reminders")

    def __repr__(self) -> str:
        return f"<Reminder lead={self.lead_id} at={self.remind_at}>"


# ─── Subscription ────────────────────────────────────────────────────────────


class Subscription(Base):
    """Razorpay subscription record tied to a user."""

    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(
        PortableUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        PortableUUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan: Mapped[str] = mapped_column(PlanEnum, nullable=False)
    razorpay_subscription_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True
    )
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="INR")
    status: Mapped[str] = mapped_column(
        SubscriptionStatusEnum, nullable=False, default="active"
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="subscriptions")

    def __repr__(self) -> str:
        return f"<Subscription {self.plan} status={self.status} user={self.user_id}>"


# ─── SyncLog ─────────────────────────────────────────────────────────────────


class SyncLog(Base):
    """Log entry for each IndiaMART lead-sync operation."""

    __tablename__ = "sync_logs"

    id: Mapped[str] = mapped_column(
        PortableUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        PortableUUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sync_type: Mapped[str] = mapped_column(SyncTypeEnum, nullable=False)
    leads_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    leads_saved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(SyncStatusEnum, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="sync_logs")

    def __repr__(self) -> str:
        return f"<SyncLog {self.sync_type} status={self.status} user={self.user_id}>"


# ─── AutoReply ───────────────────────────────────────────────────────────────


class AutoReply(Base):
    """Record of an automated reply sent to a lead."""

    __tablename__ = "auto_replies"

    id: Mapped[str] = mapped_column(
        PortableUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        PortableUUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lead_id: Mapped[str] = mapped_column(
        PortableUUID(), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reply_text: Mapped[str] = mapped_column(Text, nullable=False)
    sent_via: Mapped[str] = mapped_column(SentViaEnum, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(ReplyStatusEnum, nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="auto_replies")
    lead: Mapped["Lead"] = relationship(back_populates="auto_replies")

    def __repr__(self) -> str:
        return f"<AutoReply via={self.sent_via} status={self.status} lead={self.lead_id}>"


# ─── EmailTemplate ───────────────────────────────────────────────────────────


class EmailTemplate(Base):
    """A reusable email template belonging to a user."""

    __tablename__ = "email_templates"

    id: Mapped[str] = mapped_column(
        PortableUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        PortableUUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="email_templates")

    def __repr__(self) -> str:
        return f"<EmailTemplate {self.name!r} user={self.user_id}>"


# ─── Product ─────────────────────────────────────────────────────────────────


class Product(Base):
    """A product/service in the user's catalog for generating quotations."""

    __tablename__ = "products"

    id: Mapped[str] = mapped_column(
        PortableUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        PortableUUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    hsn_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="piece")
    base_price: Mapped[float] = mapped_column(Float, nullable=False)
    gst_rate: Mapped[float] = mapped_column(Float, nullable=False, default=18.0)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    user: Mapped["User"] = relationship("User", backref="products")

    def __repr__(self) -> str:
        return f"<Product {self.name!r} price={self.base_price} user={self.user_id}>"


# ─── Quotation ───────────────────────────────────────────────────────────────


class Quotation(Base):
    """A sales quotation generated for a buyer, optionally tied to a lead."""

    __tablename__ = "quotations"

    id: Mapped[str] = mapped_column(
        PortableUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        PortableUUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lead_id: Mapped[str | None] = mapped_column(
        PortableUUID(), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True
    )
    quotation_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)

    # Buyer details
    buyer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    buyer_company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    buyer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    buyer_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    buyer_city: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Line items as JSON string: [{product_id, name, qty, unit_price, gst_rate, total}]
    items_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    # Totals
    subtotal: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    gst_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User", backref="quotations")
    lead: Mapped["Lead | None"] = relationship("Lead", backref="quotations")

    def __repr__(self) -> str:
        return f"<Quotation {self.quotation_number} status={self.status} user={self.user_id}>"


# ─── Invoice ─────────────────────────────────────────────────────────────────


class Invoice(Base):
    """A sales invoice, optionally created from a quotation."""

    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(
        PortableUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        PortableUUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lead_id: Mapped[str | None] = mapped_column(
        PortableUUID(), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True
    )
    quotation_id: Mapped[str | None] = mapped_column(
        PortableUUID(), ForeignKey("quotations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    invoice_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)

    # Buyer details
    buyer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    buyer_company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    buyer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    buyer_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    buyer_city: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Line items as JSON string
    items_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    # Totals
    subtotal: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    gst_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    payment_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unpaid", index=True)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User", backref="invoices")
    lead: Mapped["Lead | None"] = relationship("Lead", backref="invoices")
    quotation: Mapped["Quotation | None"] = relationship("Quotation", backref="invoices")

    def __repr__(self) -> str:
        return f"<Invoice {self.invoice_number} payment={self.payment_status} user={self.user_id}>"


# ─── UserSettings ─────────────────────────────────────────────────────────────


class UserSettings(Base):
    """Extended business settings for a user (for invoices, quotations, targets)."""

    __tablename__ = "user_settings"

    id: Mapped[str] = mapped_column(
        PortableUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        PortableUUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    company_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    company_state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    company_pincode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    gst_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pan_number: Mapped[str | None] = mapped_column(String(15), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bank_account: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bank_ifsc: Mapped[str | None] = mapped_column(String(15), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    monthly_revenue_target: Mapped[float | None] = mapped_column(Float, nullable=True)
    monthly_lead_target: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationship
    user: Mapped["User"] = relationship("User", backref="settings")

    def __repr__(self) -> str:
        return f"<UserSettings user={self.user_id}>"
