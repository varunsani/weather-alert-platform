from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.alert import AlertConditionType, AlertSeverity


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    location_id: int
    severity: AlertSeverity
    condition_type: AlertConditionType
    message: str
    created_at: datetime


class AlertPushMessage(BaseModel):
    """The exact JSON shape sent down the WebSocket to subscribed clients."""

    type: str = "alert"
    location_id: int
    location_name: str
    severity: AlertSeverity
    condition_type: AlertConditionType
    message: str
    temperature_c: float
    wind_speed_kmh: float
    precipitation_mm: float
    weather_code: int
    created_at: datetime
