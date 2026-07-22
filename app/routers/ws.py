import logging

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user_ws
from app.database import get_session
from app.models.subscription import Subscription
from app.models.user import User
from app.services.connection_manager import connection_manager

router = APIRouter(tags=["websocket"])
logger = logging.getLogger(__name__)


@router.websocket("/ws/alerts")
async def websocket_alerts(
    websocket: WebSocket,
    current_user: User = Depends(get_current_user_ws),
    session: AsyncSession = Depends(get_session),
) -> None:
    """
    Live alert push, authenticated via ?token=<access_token>.

    On connect: looks up every location the user is actively subscribed
    to and registers this socket against them in the local
    ConnectionManager. When the poller (in a separate process) detects
    a severe condition for one of those locations, the message arrives
    here via Redis Pub/Sub (see services/pubsub.py) and is pushed down
    this socket in real time - no polling from the client required.
    """
    result = await session.execute(
        select(Subscription.location_id).where(
            Subscription.user_id == current_user.id,
            Subscription.is_active.is_(True),
        )
    )
    location_ids = [row[0] for row in result.all()]

    await websocket.accept()
    await connection_manager.register(websocket, location_ids)
    await websocket.send_json({
        "type": "connected",
        "message": f"Subscribed to live alerts for {len(location_ids)} location(s).",
        "location_ids": location_ids,
    })

    try:
        while True:
            # We don't require the client to send anything, but we read
            # to detect disconnects promptly and to allow simple
            # client->server pings/keepalives without extra endpoints.
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("User %s disconnected from /ws/alerts", current_user.id)
    finally:
        await connection_manager.unregister(websocket)
