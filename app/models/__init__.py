"""
Import every model module here so that:
  1. Alembic's autogenerate can see all tables via SQLModel.metadata
  2. Application code can do `from app.models import User, Location, ...`
"""

from app.models.user import User
from app.models.refresh_token import RefreshToken
from app.models.location import Location
from app.models.subscription import Subscription
from app.models.weather_reading import WeatherReading
from app.models.alert import Alert, AlertSeverity, AlertConditionType

__all__ = [
    "User",
    "RefreshToken",
    "Location",
    "Subscription",
    "WeatherReading",
    "Alert",
    "AlertSeverity",
    "AlertConditionType",
]
