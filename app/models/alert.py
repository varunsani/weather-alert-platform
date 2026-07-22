import enum
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


class AlertSeverity(str, enum.Enum):
    WATCH = "WATCH"        # conditions worth monitoring
    WARNING = "WARNING"    # conditions likely to cause disruption
    SEVERE = "SEVERE"      # dangerous conditions, take action


class AlertConditionType(str, enum.Enum):
    EXTREME_HEAT = "EXTREME_HEAT"
    EXTREME_COLD = "EXTREME_COLD"
    HIGH_WIND = "HIGH_WIND"
    HEAVY_PRECIPITATION = "HEAVY_PRECIPITATION"
    SEVERE_WEATHER_CODE = "SEVERE_WEATHER_CODE"


class Alert(SQLModel, table=True):
    """A generated alert for a location, persisted for history/audit,
    and also published to Redis for real-time push at creation time."""

    __tablename__ = "alerts"

    id: Optional[int] = Field(default=None, primary_key=True)
    location_id: int = Field(foreign_key="locations.id", nullable=False, index=True)
    reading_id: Optional[int] = Field(default=None, foreign_key="weather_readings.id")

    severity: AlertSeverity = Field(nullable=False, index=True)
    condition_type: AlertConditionType = Field(nullable=False, index=True)
    message: str = Field(nullable=False, max_length=512)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

    location: Optional["Location"] = Relationship(back_populates="alerts")
    reading: Optional["WeatherReading"] = Relationship(back_populates="alerts")
