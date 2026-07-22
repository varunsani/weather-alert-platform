"""
Thin async client around the Open-Meteo "current weather" endpoint.

No API key required. Docs: https://open-meteo.com/en/docs
We request exactly the four fields the severity engine needs, so the
poller never has to worry about parsing more than it needs.
"""

from dataclasses import dataclass

import httpx

from app.config import settings


class WeatherFetchError(Exception):
    pass


@dataclass
class CurrentWeather:
    temperature_c: float
    wind_speed_kmh: float
    precipitation_mm: float
    weather_code: int


async def fetch_current_weather(latitude: float, longitude: float) -> CurrentWeather:
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "temperature_2m,wind_speed_10m,precipitation,weather_code",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
        "timezone": "auto",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(settings.open_meteo_base_url, params=params)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise WeatherFetchError(f"Open-Meteo request failed: {exc}") from exc

    try:
        current = data["current"]
        return CurrentWeather(
            temperature_c=float(current["temperature_2m"]),
            wind_speed_kmh=float(current["wind_speed_10m"]),
            precipitation_mm=float(current["precipitation"]),
            weather_code=int(current["weather_code"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise WeatherFetchError(f"Unexpected Open-Meteo response shape: {data}") from exc
