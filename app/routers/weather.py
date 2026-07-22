import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.config import settings
from app.database import get_session
from app.models.location import Location
from app.models.user import User
from app.models.weather_reading import WeatherReading
from app.redis_client import get_redis
from app.schemas.weather import CurrentWeatherResponse, WeatherReadingRead
from app.services.weather_client import fetch_current_weather

router = APIRouter(prefix="/weather", tags=["weather"])


def _cache_key(location_id: int) -> str:
    return f"weather:location:{location_id}:current"


@router.get("/{location_id}/current", response_model=CurrentWeatherResponse)
async def get_current_weather(
    location_id: int,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    _current_user: User = Depends(get_current_user),
) -> CurrentWeatherResponse:
    """
    On-demand query for a location's current weather. Serves from a
    short-lived Redis cache first, so a burst of user queries never
    translates into a burst of upstream Open-Meteo calls.
    """
    location = await session.get(Location, location_id)
    if location is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Location not found")

    cached = await redis.get(_cache_key(location_id))
    if cached:
        data = json.loads(cached)
        return CurrentWeatherResponse(**data, cache_hit=True)

    weather = await fetch_current_weather(location.latitude, location.longitude)
    recorded_at = datetime.now(timezone.utc)

    response_data = {
        "location_id": location.id,
        "latitude": location.latitude,
        "longitude": location.longitude,
        "temperature_c": weather.temperature_c,
        "wind_speed_kmh": weather.wind_speed_kmh,
        "precipitation_mm": weather.precipitation_mm,
        "weather_code": weather.weather_code,
        "recorded_at": recorded_at.isoformat(),
    }
    await redis.setex(_cache_key(location_id), settings.weather_cache_ttl_seconds, json.dumps(response_data))

    return CurrentWeatherResponse(**response_data, cache_hit=False)


@router.get("/{location_id}/history", response_model=list[WeatherReadingRead])
async def get_weather_history(
    location_id: int,
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
) -> list[WeatherReading]:
    location = await session.get(Location, location_id)
    if location is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Location not found")

    result = await session.execute(
        select(WeatherReading)
        .where(WeatherReading.location_id == location_id)
        .order_by(WeatherReading.recorded_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
