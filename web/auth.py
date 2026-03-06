"""
JWT authentication for the JobMate web API.

Tokens are issued at session init and validated on every subsequent request
via the ``get_current_user`` FastAPI dependency.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from config.settings import SECRET_KEY
from db.database import AsyncSessionLocal
from db.models import User

ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

def create_token(user_id: int) -> str:
    """Create a signed JWT containing the user's DB id."""
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> int:
    """Decode and validate a JWT; return the user_id or raise 401."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
        return user_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token")


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

def _extract_bearer(request: Request) -> str:
    """Pull the Bearer token from the Authorization header."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")
    return auth[7:]


async def get_current_user(request: Request) -> User:
    """FastAPI dependency — validates JWT and returns the User ORM object."""
    token = _extract_bearer(request)
    user_id = decode_token(token)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user
