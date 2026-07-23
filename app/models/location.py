from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import Column, DateTime
from sqlmodel import Field, Relationship, SQLModel, UniqueConstraint


class Location(SQLModel, table=True):
    """
    A polled point on the map. Latitude/longitude are rounded to 2 decimal
    places (~1.1km precision) at creation time so that nearby subscription
    requests collapse onto the same Location row instead of creating a new
    poll target for every slightly-different coordinate.
    """

    __tablename__ = "locations"
    __table_args__ = (UniqueConstraint("latitude", "longitude", name="uq_location_lat_lon"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(nullable=False, max_length=128)
    latitude: float = Field(nullable=False, index=True)
    longitude: float = Field(nullable=False, index=True)
    timezone: Optional[str] = Field(default=None, max_length=64)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    subscriptions: List["Subscription"] = Relationship(back_populates="location")
    readings: List["WeatherReading"] = Relationship(back_populates="location")
    alerts: List["Alert"] = Relationship(back_populates="location")
