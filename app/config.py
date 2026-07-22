"""
Centralized application configuration.

Everything the app needs at runtime is read from environment variables
(see .env.example). This keeps config in one place instead of scattered
os.getenv() calls across the codebase.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_name: str = "weather-alert-platform"
    environment: str = "development"
    log_level: str = "INFO"

    # Database
    database_url: str
    database_url_sync: str

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # Weather polling (Open-Meteo)
    open_meteo_base_url: str = "https://api.open-meteo.com/v1/forecast"
    poll_interval_seconds: int = 300
    weather_cache_ttl_seconds: int = 300

    # Redis Pub/Sub
    alert_channel_prefix: str = "alerts.location"

    def alert_channel(self, location_id: int) -> str:
        return f"{self.alert_channel_prefix}.{location_id}"

    def alert_channel_pattern(self) -> str:
        return f"{self.alert_channel_prefix}.*"


settings = Settings()
