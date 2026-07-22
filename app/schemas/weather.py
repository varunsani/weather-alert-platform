from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CurrentWeatherResponse(BaseModel):
    location_id: int
    latitude: float
    longitude: float
    temperature_c: float
    wind_speed_kmh: float
    precipitation_mm: float
    weather_code: int
    recorded_at: datetime
    cache_hit: bool


class WeatherReadingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    location_id: int
    recorded_at: datetime
    temperature_c: float
    wind_speed_kmh: float
    precipitation_mm: float
    weather_code: int
