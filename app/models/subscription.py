from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime
from sqlmodel import Field, Relationship, SQLModel, UniqueConstraint


class Subscription(SQLModel, table=True):
    """A user's subscription to alerts for a given location."""

    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "location_id", name="uq_user_location"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    location_id: int = Field(foreign_key="locations.id", nullable=False, index=True)
    is_active: bool = Field(default=True, nullable=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    user: Optional["User"] = Relationship(back_populates="subscriptions")
    location: Optional["Location"] = Relationship(back_populates="subscriptions")
