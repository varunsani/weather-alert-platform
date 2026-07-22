"""
Redis Pub/Sub glue between the poller process and every API instance.

  poller  --publish--> Redis channel "alerts.location.{id}" --> every
  subscribed API instance's PubSubForwarder --> that instance's
  ConnectionManager --> only the locally-connected clients who actually
  subscribed to that location.

This is the fan-out: the poller hits the weather API exactly once per
unique location per poll cycle, no matter how many users or how many
API replicas are subscribed to it.
"""

import asyncio
import logging

from redis.asyncio import Redis

from app.config import settings
from app.schemas.alert import AlertPushMessage
from app.services.connection_manager import connection_manager

logger = logging.getLogger(__name__)


async def publish_alert(redis: Redis, message: AlertPushMessage) -> None:
    channel = settings.alert_channel(message.location_id)
    await redis.publish(channel, message.model_dump_json())


class PubSubForwarder:
    """
    One long-lived background task per API instance. Subscribes to the
    wildcard pattern once (not one subscription per location) so newly
    subscribed locations don't require re-subscribing Redis.
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._task: asyncio.Task | None = None
        self._pubsub = None

    async def start(self) -> None:
        self._pubsub = self._redis.pubsub()
        await self._pubsub.psubscribe(settings.alert_channel_pattern())
        self._task = asyncio.create_task(self._listen())
        logger.info("PubSubForwarder subscribed to pattern %s", settings.alert_channel_pattern())

    async def _listen(self) -> None:
        assert self._pubsub is not None
        try:
            async for message in self._pubsub.listen():
                if message["type"] != "pmessage":
                    continue
                channel: str = message["channel"]
                try:
                    location_id = int(channel.rsplit(".", 1)[-1])
                except ValueError:
                    logger.warning("Could not parse location_id from channel %s", channel)
                    continue

                import json
                payload = json.loads(message["data"])
                await connection_manager.broadcast_to_location(location_id, payload)
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        if self._pubsub:
            await self._pubsub.punsubscribe(settings.alert_channel_pattern())
            await self._pubsub.close()
