"""
A single shared async Redis connection pool for the whole app.

Used for three distinct purposes (all sharing one connection pool,
distinguished by key/channel naming, not separate Redis instances):
  1. JWT blacklist (SETEX jti -> "1")
  2. On-demand weather query cache (SETEX location:{id}:current -> json)
  3. Pub/Sub fan-out of alerts between the poller and API instances
"""

import redis.asyncio as redis

from app.config import settings

redis_pool = redis.ConnectionPool.from_url(settings.redis_url, decode_responses=True)


def get_redis() -> redis.Redis:
    """Return a Redis client bound to the shared connection pool."""
    return redis.Redis(connection_pool=redis_pool)
