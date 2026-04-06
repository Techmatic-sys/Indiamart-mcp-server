"""
Authentication utilities for the IndiaMART Lead Manager SaaS platform.

Provides password hashing, JWT token management, API key encryption,
and FastAPI dependency functions for route-level auth.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import bcrypt as _bcrypt_lib
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from saas.config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=True)

# Fernet key for encrypting IndiaMART API keys at rest.
# In production, set FERNET_KEY env var to a stable key generated via
# `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
_FERNET_KEY: str = os.getenv("FERNET_KEY", "")
if not _FERNET_KEY:
    # Derive a deterministic key from SECRET_KEY so it stays stable across restarts.
    import base64
    import hashlib

    _derived = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    _FERNET_KEY = base64.urlsafe_b64encode(_derived).decode()

_fernet = Fernet(_FERNET_KEY.encode())

# ---------------------------------------------------------------------------
# Refresh-token settings
# ---------------------------------------------------------------------------

REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against its bcrypt hash."""
    return _bcrypt_lib.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def get_password_hash(password: str) -> str:
    """Return a bcrypt hash of the given password."""
    salt = _bcrypt_lib.gensalt()
    return _bcrypt_lib.hashpw(password.encode("utf-8"), salt).decode("utf-8")


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_access_token(
    data: dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a signed JWT access token.

    Args:
        data: Claims to embed (must include ``sub`` with the user id).
        expires_delta: Custom lifetime; defaults to ``ACCESS_TOKEN_EXPIRE_MINUTES``.

    Returns:
        Encoded JWT string.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta
        if expires_delta
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(data: dict[str, Any]) -> str:
    """Create a signed JWT refresh token with a 7-day expiry.

    Args:
        data: Claims to embed (must include ``sub`` with the user id).

    Returns:
        Encoded JWT string.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT token, returning its payload.

    Raises:
        JWTError: If the token is invalid, expired, or tampered with.
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


# ---------------------------------------------------------------------------
# API-key encryption (Fernet)
# ---------------------------------------------------------------------------

def encrypt_api_key(api_key: str) -> str:
    """Encrypt an IndiaMART API key for safe storage.

    Args:
        api_key: The plain-text API key.

    Returns:
        Base64-encoded encrypted string.
    """
    return _fernet.encrypt(api_key.encode()).decode()


def decrypt_api_key(encrypted_key: str) -> str:
    """Decrypt a previously encrypted IndiaMART API key.

    Args:
        encrypted_key: The encrypted string from :func:`encrypt_api_key`.

    Returns:
        The original plain-text API key.

    Raises:
        ValueError: If decryption fails (corrupted or wrong key).
    """
    try:
        return _fernet.decrypt(encrypted_key.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Failed to decrypt API key — key may be corrupted or FERNET_KEY changed.") from exc


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

async def get_current_user(
    token: str = Depends(oauth2_scheme),
) -> Any:
    """FastAPI dependency: extract and return the User from a valid JWT.

    Uses a late import of ``saas.database`` and ``saas.models`` to avoid
    circular-import issues at module load time.

    Raises:
        HTTPException 401: If the token is invalid or the user doesn't exist.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise credentials_exception
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    # Late imports to break circular dependency
    from saas.database import async_session_factory
    from saas.models import User

    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    return user


async def get_current_active_user(
    current_user: Any = Depends(get_current_user),
) -> Any:
    """FastAPI dependency: ensure the authenticated user's account is active.

    Raises:
        HTTPException 403: If the user account is deactivated.
    """
    if not getattr(current_user, "is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated.",
        )
    return current_user
