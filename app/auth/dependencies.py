from fastapi import Depends, HTTPException, WebSocket, WebSocketException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.blacklist import is_blacklisted
from app.auth.jwt_handler import InvalidTokenError, decode_token
from app.database import get_session
from app.models.user import User
from app.redis_client import get_redis

bearer_scheme = HTTPBearer(auto_error=False)


async def _load_active_user(session: AsyncSession, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> User:
    """Validates the access token on every protected HTTP route."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        payload = decode_token(credentials.credentials)
    except InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    if payload.type != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Expected an access token")

    if await is_blacklisted(redis, payload.jti):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked")

    return await _load_active_user(session, int(payload.sub))


async def get_current_user_ws(
    websocket: WebSocket,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> User:
    """
    Validates the access token passed as a query parameter on the WebSocket
    handshake (?token=...). Raises WebSocketException so the caller can
    close the connection with a proper close code before accepting it.
    """
    token = websocket.query_params.get("token")
    if not token:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Missing token")

    try:
        payload = decode_token(token)
    except InvalidTokenError:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid or expired token")

    if payload.type != "access":
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Expected an access token")

    if await is_blacklisted(redis, payload.jti):
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Token has been revoked")

    try:
        return await _load_active_user(session, int(payload.sub))
    except HTTPException:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="User not found or inactive")
