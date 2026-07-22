"""
Access + refresh token creation and verification.

Both token types carry a unique `jti` (JWT ID) so that:
  - a specific token can be blacklisted in Redis on logout
  - refresh tokens can be tracked/revoked individually in Postgres

Token payload shape:
  {
    "sub": "<user_id>",
    "jti": "<uuid4>",
    "type": "access" | "refresh",
    "exp": <unix timestamp>,
    "iat": <unix timestamp>,
  }
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from jose import JWTError, jwt
from pydantic import BaseModel

from app.config import settings


class TokenPayload(BaseModel):
    sub: str
    jti: str
    type: Literal["access", "refresh"]
    exp: datetime
    iat: datetime


class InvalidTokenError(Exception):
    pass


def _create_token(user_id: int, token_type: Literal["access", "refresh"], expires_delta: timedelta) -> tuple[str, str, datetime]:
    now = datetime.now(timezone.utc)
    expire = now + expires_delta
    jti = str(uuid.uuid4())
    payload = {
        "sub": str(user_id),
        "jti": jti,
        "type": token_type,
        "exp": expire,
        "iat": now,
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, jti, expire


def create_access_token(user_id: int) -> tuple[str, str, datetime]:
    """Returns (token, jti, expires_at)."""
    return _create_token(user_id, "access", timedelta(minutes=settings.access_token_expire_minutes))


def create_refresh_token(user_id: int) -> tuple[str, str, datetime]:
    """Returns (token, jti, expires_at)."""
    return _create_token(user_id, "refresh", timedelta(days=settings.refresh_token_expire_days))


def decode_token(token: str) -> TokenPayload:
    try:
        raw = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        return TokenPayload(**raw)
    except JWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
