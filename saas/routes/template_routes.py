"""
Email / message template CRUD API endpoints.

Manage reusable message templates scoped to each user.
All routes require authentication via ``get_current_active_user``.
Mounted under ``/api`` by the main FastAPI application.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from saas.auth import get_current_active_user
from saas.database import async_session_factory
from saas.models import EmailTemplate, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["templates"])

# ─── Request Schemas ─────────────────────────────────────────────────────────


class TemplateCreateRequest(BaseModel):
    """Body for creating a new template."""

    name: str = Field(..., min_length=1, max_length=255, description="Template name")
    subject: Optional[str] = Field(None, max_length=500, description="Email subject line")
    body: str = Field(..., min_length=1, description="Template body / content")
    template_type: Optional[str] = Field(
        "email",
        description="Template type: email, whatsapp, sms",
    )


class TemplateUpdateRequest(BaseModel):
    """Body for updating an existing template (all fields optional)."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    subject: Optional[str] = Field(None, max_length=500)
    body: Optional[str] = Field(None, min_length=1)
    template_type: Optional[str] = None


# ─── Dependency shorthand ────────────────────────────────────────────────────

CurrentUser = Depends(get_current_active_user)


# ─── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/templates")
async def list_templates(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    template_type: Optional[str] = Query(None),
    user: User = CurrentUser,
) -> dict[str, Any]:
    """List all templates for the authenticated user.

    Args:
        page: Page number (1-indexed).
        per_page: Results per page.
        template_type: Optional filter by template type.
        user: Authenticated user.

    Returns:
        Paginated list of templates.
    """
    offset = (page - 1) * per_page

    async with async_session_factory() as session:
        base = select(EmailTemplate).where(EmailTemplate.user_id == user.id)
        count_q = select(func.count()).select_from(EmailTemplate).where(EmailTemplate.user_id == user.id)

        if template_type:
            base = base.where(EmailTemplate.template_type == template_type)
            count_q = count_q.where(EmailTemplate.template_type == template_type)

        total = (await session.execute(count_q)).scalar() or 0

        rows = (
            await session.execute(
                base.order_by(EmailTemplate.created_at.desc()).offset(offset).limit(per_page)
            )
        ).scalars().all()

    return {
        "templates": [_template_to_dict(t) for t in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max((total + per_page - 1) // per_page, 1),
    }


@router.post("/templates", status_code=status.HTTP_201_CREATED)
async def create_template(
    body: TemplateCreateRequest,
    user: User = CurrentUser,
) -> dict[str, Any]:
    """Create a new template for the authenticated user.

    Args:
        body: Template content.
        user: Authenticated user.

    Returns:
        The created template record.
    """
    async with async_session_factory() as session:
        template = EmailTemplate(
            user_id=user.id,
            name=body.name,
            subject=body.subject,
            body=body.body,
            template_type=body.template_type or "email",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(template)
        await session.commit()
        await session.refresh(template)

    logger.info("Template '%s' (%s) created by user %s", template.name, template.id, user.id)

    return _template_to_dict(template)


@router.get("/templates/{template_id}")
async def get_template(
    template_id: uuid.UUID,
    user: User = CurrentUser,
) -> dict[str, Any]:
    """Get a single template by ID.

    Args:
        template_id: UUID of the template.
        user: Authenticated user (must own the template).

    Returns:
        Template record.

    Raises:
        HTTPException 404: If the template is not found.
    """
    async with async_session_factory() as session:
        result = await session.execute(
            select(EmailTemplate).where(
                EmailTemplate.id == str(template_id),
                EmailTemplate.user_id == user.id,
            )
        )
        template = result.scalar_one_or_none()

    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    return _template_to_dict(template)


@router.put("/templates/{template_id}")
async def update_template(
    template_id: uuid.UUID,
    body: TemplateUpdateRequest,
    user: User = CurrentUser,
) -> dict[str, Any]:
    """Update an existing template.

    Args:
        template_id: UUID of the template.
        body: Fields to update (only provided fields are changed).
        user: Authenticated user (must own the template).

    Returns:
        Updated template record.

    Raises:
        HTTPException 404: If the template is not found.
    """
    async with async_session_factory() as session:
        result = await session.execute(
            select(EmailTemplate).where(
                EmailTemplate.id == str(template_id),
                EmailTemplate.user_id == user.id,
            )
        )
        template = result.scalar_one_or_none()

        if template is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

        if body.name is not None:
            template.name = body.name
        if body.subject is not None:
            template.subject = body.subject
        if body.body is not None:
            template.body = body.body
        if body.template_type is not None:
            template.template_type = body.template_type

        template.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(template)

    return _template_to_dict(template)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: uuid.UUID,
    user: User = CurrentUser,
) -> None:
    """Delete a template.

    Args:
        template_id: UUID of the template.
        user: Authenticated user (must own the template).

    Raises:
        HTTPException 404: If the template is not found.
    """
    async with async_session_factory() as session:
        result = await session.execute(
            select(EmailTemplate).where(
                EmailTemplate.id == str(template_id),
                EmailTemplate.user_id == user.id,
            )
        )
        template = result.scalar_one_or_none()

        if template is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

        await session.delete(template)
        await session.commit()

    logger.info("Template %s deleted by user %s", template_id, user.id)


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _template_to_dict(template: EmailTemplate) -> dict[str, Any]:
    """Serialize an EmailTemplate ORM object to a dict."""
    return {
        "id": str(template.id),
        "user_id": str(template.user_id),
        "name": template.name,
        "subject": getattr(template, "subject", None),
        "body": template.body,
        "template_type": getattr(template, "template_type", "email"),
        "created_at": template.created_at.isoformat() if template.created_at else None,
        "updated_at": template.updated_at.isoformat() if getattr(template, "updated_at", None) else None,
    }
