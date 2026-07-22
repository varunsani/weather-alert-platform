"""
Severity classification engine.

Turns a raw weather reading into zero or more Alerts. Every threshold
lives in the two dicts below (SEVERITY_RULES and WEATHER_CODE_SEVERITY)
so tuning the sensitivity of the system never requires touching the
evaluation logic itself - just the numbers/mappings.

Design choice: for each *category* (temperature, wind, precipitation,
weather-code) we emit at most one alert, at the highest severity tier
that the reading crosses. This keeps a single severe thunderstorm from
generating five overlapping alerts for the same reading.
"""

from dataclasses import dataclass
from typing import Optional

from app.models.alert import AlertConditionType, AlertSeverity
from app.services.weather_client import CurrentWeather

# ---------------------------------------------------------------------------
# Tunable thresholds. Values are the point at which a tier is *entered*.
# Ordered WATCH -> WARNING -> SEVERE; a reading is classified at the
# highest tier whose threshold it meets or exceeds.
# ---------------------------------------------------------------------------
SEVERITY_RULES = {
    "extreme_heat_c": {
        AlertSeverity.WATCH: 32.0,
        AlertSeverity.WARNING: 38.0,
        AlertSeverity.SEVERE: 44.0,
    },
    "extreme_cold_c": {
        AlertSeverity.WATCH: 0.0,     # at or below
        AlertSeverity.WARNING: -10.0,
        AlertSeverity.SEVERE: -20.0,
    },
    "high_wind_kmh": {
        AlertSeverity.WATCH: 40.0,
        AlertSeverity.WARNING: 65.0,
        AlertSeverity.SEVERE: 90.0,
    },
    "heavy_precipitation_mm": {
        AlertSeverity.WATCH: 7.5,
        AlertSeverity.WARNING: 15.0,
        AlertSeverity.SEVERE: 30.0,
    },
}

# WMO weather codes (as used by Open-Meteo) mapped to a severity tier.
# Codes not present here are considered benign (clear/cloudy) and never alert.
WEATHER_CODE_SEVERITY: dict[int, AlertSeverity] = {
    45: AlertSeverity.WATCH, 48: AlertSeverity.WATCH,        # fog
    51: AlertSeverity.WATCH, 53: AlertSeverity.WATCH, 55: AlertSeverity.WATCH,  # drizzle
    71: AlertSeverity.WATCH, 73: AlertSeverity.WATCH,        # snow slight/moderate
    80: AlertSeverity.WATCH,                                  # rain showers slight
    61: AlertSeverity.WARNING, 63: AlertSeverity.WARNING, 65: AlertSeverity.WARNING,  # rain
    66: AlertSeverity.WARNING, 67: AlertSeverity.WARNING,     # freezing rain
    75: AlertSeverity.WARNING,                                # heavy snow
    81: AlertSeverity.WARNING, 82: AlertSeverity.WARNING,     # rain showers mod/violent
    85: AlertSeverity.WARNING, 86: AlertSeverity.WARNING,     # snow showers
    95: AlertSeverity.WARNING,                                # thunderstorm slight/moderate
    96: AlertSeverity.SEVERE, 99: AlertSeverity.SEVERE,       # thunderstorm with hail
}

WEATHER_CODE_LABELS: dict[int, str] = {
    45: "fog", 48: "depositing rime fog",
    51: "light drizzle", 53: "moderate drizzle", 55: "dense drizzle",
    61: "slight rain", 63: "moderate rain", 65: "heavy rain",
    66: "freezing rain", 67: "heavy freezing rain",
    71: "slight snowfall", 73: "moderate snowfall", 75: "heavy snowfall",
    80: "slight rain showers", 81: "moderate rain showers", 82: "violent rain showers",
    85: "slight snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with slight hail", 99: "thunderstorm with heavy hail",
}


@dataclass
class ClassifiedAlert:
    severity: AlertSeverity
    condition_type: AlertConditionType
    message: str


def _highest_tier_met(value: float, thresholds: dict[AlertSeverity, float], reverse: bool = False) -> Optional[AlertSeverity]:
    """
    Returns the highest severity tier whose threshold `value` meets.
    reverse=True means "at or below" (used for cold), otherwise "at or above".
    """
    met: Optional[AlertSeverity] = None
    for tier in (AlertSeverity.WATCH, AlertSeverity.WARNING, AlertSeverity.SEVERE):
        threshold = thresholds[tier]
        crossed = (value <= threshold) if reverse else (value >= threshold)
        if crossed:
            met = tier
    return met


def classify(reading: CurrentWeather, location_name: str) -> list[ClassifiedAlert]:
    """Evaluate one reading against every rule category. Returns 0-N alerts."""
    alerts: list[ClassifiedAlert] = []

    # --- Temperature: heat and cold are mutually exclusive, check both ---
    heat_tier = _highest_tier_met(reading.temperature_c, SEVERITY_RULES["extreme_heat_c"])
    if heat_tier:
        alerts.append(ClassifiedAlert(
            severity=heat_tier,
            condition_type=AlertConditionType.EXTREME_HEAT,
            message=f"Extreme heat {heat_tier.value.lower()} for {location_name}: "
                    f"{reading.temperature_c:.1f}\u00b0C",
        ))

    cold_tier = _highest_tier_met(reading.temperature_c, SEVERITY_RULES["extreme_cold_c"], reverse=True)
    if cold_tier:
        alerts.append(ClassifiedAlert(
            severity=cold_tier,
            condition_type=AlertConditionType.EXTREME_COLD,
            message=f"Extreme cold {cold_tier.value.lower()} for {location_name}: "
                    f"{reading.temperature_c:.1f}\u00b0C",
        ))

    # --- Wind ---
    wind_tier = _highest_tier_met(reading.wind_speed_kmh, SEVERITY_RULES["high_wind_kmh"])
    if wind_tier:
        alerts.append(ClassifiedAlert(
            severity=wind_tier,
            condition_type=AlertConditionType.HIGH_WIND,
            message=f"High wind {wind_tier.value.lower()} for {location_name}: "
                    f"{reading.wind_speed_kmh:.1f} km/h",
        ))

    # --- Precipitation ---
    precip_tier = _highest_tier_met(reading.precipitation_mm, SEVERITY_RULES["heavy_precipitation_mm"])
    if precip_tier:
        alerts.append(ClassifiedAlert(
            severity=precip_tier,
            condition_type=AlertConditionType.HEAVY_PRECIPITATION,
            message=f"Heavy precipitation {precip_tier.value.lower()} for {location_name}: "
                    f"{reading.precipitation_mm:.1f} mm/h",
        ))

    # --- Weather code (fog, storms, hail, etc.) ---
    code_tier = WEATHER_CODE_SEVERITY.get(reading.weather_code)
    if code_tier:
        label = WEATHER_CODE_LABELS.get(reading.weather_code, f"code {reading.weather_code}")
        alerts.append(ClassifiedAlert(
            severity=code_tier,
            condition_type=AlertConditionType.SEVERE_WEATHER_CODE,
            message=f"Severe weather {code_tier.value.lower()} for {location_name}: {label}",
        ))

    return alerts
