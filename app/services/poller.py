"""
The poller: a single dedicated process (see scripts/run_poller.py and the
`poller` service in docker-compose.yml) that is the *only* thing calling
the Open-Meteo API.

Loop, every POLL_INTERVAL_SECONDS:
  1. Ask Postgres for the distinct set of locations that have at least
     one active subscription (no point polling a location nobody cares
     about).
  2. For each location, fetch current weather, persist it as a
     WeatherReading (time-series row).
  3. Run it through the severity engine. For every alert produced,
     persist it and publish it to Redis so every API instance can push
     it to its connected, subscribed clients.

Running this as one process (not scaled) is deliberate: it's what
guarantees each location is polled exactly once per cycle regardless of
how many API replicas or how many subscribers exist.
"""

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.alert import Alert
from app.models.location import Location
from app.models.subscription import Subscription
from app.models.weather_reading import WeatherReading
from app.redis_client import get_redis
from app.schemas.alert import AlertPushMessage
from app.services.pubsub import publish_alert
from app.services.severity_engine import classify
from app.services.weather_client import WeatherFetchError, fetch_current_weather

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("poller")


async def get_actively_subscribed_locations(session: AsyncSession) -> list[Location]:
    stmt = (
        select(Location)
        .join(Subscription, Subscription.location_id == Location.id)
        .where(Subscription.is_active.is_(True))
        .distinct()
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def poll_location_once(session: AsyncSession, redis, location: Location) -> None:
    try:
        weather = await fetch_current_weather(location.latitude, location.longitude)
    except WeatherFetchError:
        logger.exception("Failed to fetch weather for location %s (%s)", location.id, location.name)
        return

    reading = WeatherReading(
        location_id=location.id,
        temperature_c=weather.temperature_c,
        wind_speed_kmh=weather.wind_speed_kmh,
        precipitation_mm=weather.precipitation_mm,
        weather_code=weather.weather_code,
    )
    session.add(reading)
    await session.flush()  # populate reading.id without committing yet

    classified = classify(weather, location.name)

    for item in classified:
        alert = Alert(
            location_id=location.id,
            reading_id=reading.id,
            severity=item.severity,
            condition_type=item.condition_type,
            message=item.message,
        )
        session.add(alert)

    await session.commit()

    for item in classified:
        push = AlertPushMessage(
            location_id=location.id,
            location_name=location.name,
            severity=item.severity,
            condition_type=item.condition_type,
            message=item.message,
            temperature_c=weather.temperature_c,
            wind_speed_kmh=weather.wind_speed_kmh,
            precipitation_mm=weather.precipitation_mm,
            weather_code=weather.weather_code,
            created_at=reading.recorded_at,
        )
        await publish_alert(redis, push)
        logger.info("Published %s/%s alert for location %s", item.severity, item.condition_type, location.id)


async def poll_cycle() -> None:
    redis = get_redis()
    async with AsyncSessionLocal() as session:
        locations = await get_actively_subscribed_locations(session)
        logger.info("Polling %d actively-subscribed location(s)", len(locations))
        for location in locations:
            await poll_location_once(session, redis, location)


async def run_poller() -> None:
    logger.info("Poller starting. Interval=%ss", settings.poll_interval_seconds)
    while True:
        try:
            await poll_cycle()
        except Exception:
            logger.exception("Unhandled error during poll cycle")
        await asyncio.sleep(settings.poll_interval_seconds)


if __name__ == "__main__":
    asyncio.run(run_poller())
