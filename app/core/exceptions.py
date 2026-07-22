from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.services.weather_client import WeatherFetchError


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(WeatherFetchError)
    async def weather_fetch_error_handler(request: Request, exc: WeatherFetchError) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={"detail": f"Upstream weather provider error: {exc}"},
        )
