from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import Column, DateTime
from sqlmodel import Field, Relationship, SQLModel


class WeatherReading(SQLModel, table=True):
    """
    One row per poll of one location. Append-only time series -
    never updated after insert, which is what makes it cheap to index
    on (location_id, recorded_at) for history queries.
    """

    __tablename__ = "weather_readings"

    id: Optional[int] = Field(default=None, primary_key=True)
    location_id: int = Field(foreign_key="locations.id", nullable=False, index=True)
    recorded_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )

    temperature_c: float = Field(nullable=False)
    wind_speed_kmh: float = Field(nullable=False)
    precipitation_mm: float = Field(nullable=False)
    weather_code: int = Field(nullable=False)

    location: Optional["Location"] = Relationship(back_populates="readings")
    alerts: List["Alert"] = Relationship(back_populates="reading")
