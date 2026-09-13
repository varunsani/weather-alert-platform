import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.core.exceptions import register_exception_handlers
from app.redis_client import get_redis
from app.routers import auth, locations, subscriptions, weather, ws
from app.services.pubsub import PubSubForwarder

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Each API instance runs its own PubSubForwarder: it subscribes once
    # to the alert channel pattern and forwards messages to whichever
    # clients are connected *to this instance*. This is what lets you
    # scale the `api` service to N replicas behind a load balancer while
    # the poller remains a single source of truth for polling.
    redis = get_redis()
    forwarder = PubSubForwarder(redis)
    await forwarder.start()
    logger.info("API instance ready. PubSub forwarder running.")

    yield

    await forwarder.stop()
    await redis.aclose()



app = FastAPI(
    title=settings.app_name,
    description="Real-time weather alerting platform: WebSocket push, Redis fan-out, JWT auth, Postgres time-series.",
    version="1.0.0",
    lifespan=lifespan,
)

register_exception_handlers(app)

app.include_router(auth.router)
app.include_router(locations.router)
app.include_router(subscriptions.router)
app.include_router(weather.router)
app.include_router(ws.router)


app.mount("/static", StaticFiles(directory="app/static", html=True), name="static")


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok"}


@app.get("/")
async def root():
    from fastapi.responses import FileResponse
    return FileResponse("app/static/test_client.html")
