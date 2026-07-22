"""
Tracks *local* WebSocket connections on this particular API instance,
indexed by which location_ids each connected user cares about.

This is intentionally in-memory and per-process: with N scaled API
replicas, each replica only knows about its own connected clients.
That's exactly why the poller doesn't talk to clients directly - it
publishes to Redis, and every replica's PubSubForwarder (see pubsub.py)
independently fans out to whichever of *its* clients are subscribed.
"""

import asyncio
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        # location_id -> set of live websocket connections subscribed to it
        self._by_location: dict[int, set[WebSocket]] = {}
        # websocket -> the set of location_ids it's registered for (for cleanup)
        self._by_socket: dict[WebSocket, set[int]] = {}
        self._lock = asyncio.Lock()

    async def register(self, websocket: WebSocket, location_ids: list[int]) -> None:
        async with self._lock:
            self._by_socket[websocket] = set(location_ids)
            for loc_id in location_ids:
                self._by_location.setdefault(loc_id, set()).add(websocket)

    async def unregister(self, websocket: WebSocket) -> None:
        async with self._lock:
            location_ids = self._by_socket.pop(websocket, set())
            for loc_id in location_ids:
                sockets = self._by_location.get(loc_id)
                if sockets:
                    sockets.discard(websocket)
                    if not sockets:
                        del self._by_location[loc_id]

    def active_location_ids(self) -> list[int]:
        """All location_ids that have at least one locally-connected client."""
        return list(self._by_location.keys())

    async def broadcast_to_location(self, location_id: int, payload: dict) -> None:
        sockets = list(self._by_location.get(location_id, ()))
        for ws in sockets:
            try:
                await ws.send_json(payload)
            except Exception:
                logger.warning("Failed to push to a socket for location %s; unregistering it", location_id)
                await self.unregister(ws)


# Single shared instance per process/app worker.
connection_manager = ConnectionManager()
