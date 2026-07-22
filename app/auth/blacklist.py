"""
Redis-backed JWT blacklist.

On logout (or refresh-token rotation) a token's `jti` is written to Redis
with a TTL equal to its *remaining* lifetime - so the blacklist entry
disappears on its own exactly when the token would have expired anyway.
Every access-protected request and every refresh attempt checks this set.
"""

from datetime import datetime, timezone

from redis.asyncio import Redis

BLACKLIST_KEY_PREFIX = "blacklist:jti"


def _key(jti: str) -> str:
    return f"{BLACKLIST_KEY_PREFIX}:{jti}"


async def blacklist_token(redis: Redis, jti: str, expires_at: datetime) -> None:
    ttl_seconds = int((expires_at - datetime.now(timezone.utc)).total_seconds())
    if ttl_seconds > 0:
        await redis.setex(_key(jti), ttl_seconds, "1")


async def is_blacklisted(redis: Redis, jti: str) -> bool:
    return (await redis.exists(_key(jti))) == 1
