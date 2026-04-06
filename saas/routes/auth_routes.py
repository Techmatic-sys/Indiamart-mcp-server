"""
Authentication API routes for the IndiaMART Lead Manager SaaS platform.

Endpoints for signup, login, token refresh, profile management,
API-key storage, and password reset.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from saas.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    decrypt_api_key,
    encrypt_api_key,
    get_current_active_user,
    get_password_hash,
    verify_password,
)
from saas.database import get_db
from saas.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Pydantic request / response schemas
# ---------------------------------------------------------------------------

class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    name: str = Field(..., min_length=1, max_length=200)
    company_name: Optional[str] = Field(None, max_length=300)
    phone: Optional[str] = Field(None, max_length=20)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    company_name: Optional[str] = None
    phone: Optional[str] = None
    plan: str
    is_active: bool
    has_api_key: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class UpdateProfileRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    company_name: Optional[str] = Field(None, max_length=300)
    phone: Optional[str] = Field(None, max_length=20)


class ApiKeyRequest(BaseModel):
    api_key: str = Field(..., min_length=1)


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=8, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8, max_length=128)


class MessageResponse(BaseModel):
    message: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_response(user: User) -> UserResponse:
    """Build a :class:`UserResponse` from a SQLAlchemy ``User`` model."""
    return UserResponse(
        id=str(user.id),
        email=user.email,
        name=user.name,
        company_name=user.company_name,
        phone=user.phone,
        plan=user.plan,
        is_active=user.is_active,
        has_api_key=bool(user.indiamart_api_key),
        created_at=user.created_at,
    )


def _token_pair(user_id: str) -> dict[str, str]:
    """Generate an access + refresh token pair for the given user id."""
    return {
        "access_token": create_access_token({"sub": user_id}),
        "refresh_token": create_refresh_token({"sub": user_id}),
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post(
    "/signup",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new account",
)
async def signup(body: SignupRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    """Register a new user.

    Returns JWT tokens and user profile on success.
    Returns 409 if the email is already registered.
    """
    # Check email uniqueness
    result = await db.execute(select(User).where(User.email == body.email.lower()))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    user = User(
        id=str(uuid4()),
        email=body.email.lower(),
        password_hash=get_password_hash(body.password),
        name=body.name,
        company_name=body.company_name,
        phone=body.phone,
        plan="free",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    tokens = _token_pair(str(user.id))
    return AuthResponse(
        **tokens,
        token_type="bearer",
        user=_user_response(user),
    )


@router.post(
    "/login",
    response_model=AuthResponse,
    summary="Login with email and password",
)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    """Authenticate a user and return JWT tokens.

    Returns 401 for invalid credentials.
    """
    result = await db.execute(select(User).where(User.email == body.email.lower()))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated.",
        )

    tokens = _token_pair(str(user.id))
    return AuthResponse(
        **tokens,
        token_type="bearer",
        user=_user_response(user),
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh an access token",
)
async def refresh_token(body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    """Exchange a valid refresh token for a new access + refresh pair.

    Returns 401 if the refresh token is invalid or expired.
    """
    from jose import JWTError

    try:
        payload = decode_token(body.refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type — expected a refresh token.",
            )
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token.",
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
        )

    # Verify user still exists and is active
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated.",
        )

    tokens = _token_pair(str(user.id))
    return TokenResponse(**tokens)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile",
)
async def get_me(current_user: User = Depends(get_current_active_user)) -> UserResponse:
    """Return the authenticated user's profile."""
    return _user_response(current_user)


@router.put(
    "/me",
    response_model=UserResponse,
    summary="Update current user profile",
)
async def update_me(
    body: UpdateProfileRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Update name, company, or phone for the authenticated user."""
    updates: dict[str, Any] = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.company_name is not None:
        updates["company_name"] = body.company_name
    if body.phone is not None:
        updates["phone"] = body.phone

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update.",
        )

    await db.execute(
        update(User).where(User.id == current_user.id).values(**updates)
    )
    await db.commit()

    # Re-fetch to get updated values
    result = await db.execute(select(User).where(User.id == current_user.id))
    user = result.scalar_one()
    return _user_response(user)


@router.put(
    "/api-key",
    response_model=MessageResponse,
    summary="Save or update IndiaMART API key",
)
async def save_api_key(
    body: ApiKeyRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Encrypt and store the user's IndiaMART API key."""
    encrypted = encrypt_api_key(body.api_key)
    await db.execute(
        update(User)
        .where(User.id == current_user.id)
        .values(indiamart_api_key=encrypted)
    )
    await db.commit()
    return MessageResponse(message="API key saved successfully.")


@router.post(
    "/change-password",
    response_model=MessageResponse,
    summary="Change password",
)
async def change_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Change the authenticated user's password.

    Requires the current (old) password for verification.
    """
    if not verify_password(body.old_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )

    new_hash = get_password_hash(body.new_password)
    await db.execute(
        update(User)
        .where(User.id == current_user.id)
        .values(password_hash=new_hash)
    )
    await db.commit()
    return MessageResponse(message="Password changed successfully.")


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    summary="Request a password reset",
)
async def forgot_password(
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Generate a password-reset token for the given email.

    Always returns 200 to avoid leaking whether an email is registered.
    In production, the token would be sent via email.
    """
    result = await db.execute(select(User).where(User.email == body.email.lower()))
    user = result.scalar_one_or_none()

    if user is not None:
        reset_token = secrets.token_urlsafe(32)
        reset_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
        await db.execute(
            update(User)
            .where(User.id == user.id)
            .values(
                reset_token=reset_token,
                reset_token_expires=reset_expiry,
            )
        )
        await db.commit()

        # TODO: Send email with reset link containing `reset_token`.
        # For now we log it (remove in production).
        import logging

        logging.getLogger(__name__).info(
            "Password reset token for %s: %s (expires %s)",
            user.email,
            reset_token,
            reset_expiry.isoformat(),
        )

    # Always return the same message regardless of whether user exists.
    return MessageResponse(
        message="If that email is registered, a password reset link has been sent."
    )


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    summary="Reset password with token",
)
async def reset_password(
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Reset a user's password using a valid reset token."""
    result = await db.execute(
        select(User).where(User.reset_token == body.token)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token.",
        )

    # Check expiry
    if (
        user.reset_token_expires is None
        or user.reset_token_expires < datetime.now(timezone.utc)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token.",
        )

    new_hash = get_password_hash(body.new_password)
    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(
            password_hash=new_hash,
            reset_token=None,
            reset_token_expires=None,
        )
    )
    await db.commit()
    return MessageResponse(message="Password has been reset successfully.")
