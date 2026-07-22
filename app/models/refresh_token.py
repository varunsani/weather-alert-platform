from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


class RefreshToken(SQLModel, table=True):
    """
    Tracks issued refresh tokens so a user's sessions can be enumerated
    and individually or entirely revoked (e.g. "log out of all devices").

    The Redis blacklist (app/auth/blacklist.py) is the fast-path check
    on every request; this table is the source of truth / audit trail.
    """

    __tablename__ = "refresh_tokens"

    id: Optional[int] = Field(default=None, primary_key=True)
    jti: str = Field(index=True, unique=True, nullable=False, max_length=64)
    user_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    issued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = Field(nullable=False)
    revoked: bool = Field(default=False, nullable=False)

    user: Optional["User"] = Relationship(back_populates="refresh_tokens")
