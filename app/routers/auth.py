from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.blacklist import blacklist_token, is_blacklisted
from app.auth.jwt_handler import InvalidTokenError, create_access_token, create_refresh_token, decode_token
from app.auth.password import hash_password, verify_password
from app.database import get_session
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.redis_client import get_redis
from app.schemas.auth import AccessTokenOnly, LoginRequest, LogoutRequest, RefreshRequest, RegisterRequest, TokenPair
from app.schemas.user import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])
bearer_scheme = HTTPBearer(auto_error=False)


async def _issue_token_pair(session: AsyncSession, user_id: int) -> TokenPair:
    access_token, _, _ = create_access_token(user_id)
    refresh_token, refresh_jti, refresh_expires = create_refresh_token(user_id)

    session.add(RefreshToken(jti=refresh_jti, user_id=user_id, expires_at=refresh_expires))
    await session.commit()

    return TokenPair(access_token=access_token, refresh_token=refresh_token)


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, session: AsyncSession = Depends(get_session)) -> User:
    existing = await session.execute(
        select(User).where((User.username == payload.username) | (User.email == payload.email))
    )
    if existing.scalars().first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username or email already registered")

    user = User(username=payload.username, email=payload.email, hashed_password=hash_password(payload.password))
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.post("/login", response_model=TokenPair)
async def login(payload: LoginRequest, session: AsyncSession = Depends(get_session)) -> TokenPair:
    result = await session.execute(select(User).where(User.username == payload.username))
    user = result.scalars().first()

    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")

    return await _issue_token_pair(session, user.id)


@router.post("/refresh", response_model=AccessTokenOnly)
async def refresh(
    payload: RefreshRequest,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> AccessTokenOnly:
    """
    Rotates the refresh token: the presented refresh token is immediately
    blacklisted and revoked in the DB, and a fresh access token is issued.
    (Full rotation - i.e. also issuing a brand new refresh token - is left
    as a one-line extension; here we keep the existing refresh token's
    DB row as the single source of truth and just mint a new access token
    guarded by the same blacklist check.)
    """
    try:
        token_payload = decode_token(payload.refresh_token)
    except InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    if token_payload.type != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Expected a refresh token")

    if await is_blacklisted(redis, token_payload.jti):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token has been revoked")

    result = await session.execute(select(RefreshToken).where(RefreshToken.jti == token_payload.jti))
    stored = result.scalars().first()
    if stored is None or stored.revoked or stored.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token no longer valid")

    access_token, _, _ = create_access_token(int(token_payload.sub))
    return AccessTokenOnly(access_token=access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: LogoutRequest,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> None:
    """Blacklists the presented access token (if any) and the refresh token, and revokes the refresh token in the DB."""
    if credentials is not None:
        try:
            access_payload = decode_token(credentials.credentials)
            if access_payload.type == "access":
                await blacklist_token(redis, access_payload.jti, access_payload.exp)
        except InvalidTokenError:
            pass  # already invalid/expired; nothing to blacklist

    try:
        refresh_payload = decode_token(payload.refresh_token)
    except InvalidTokenError:
        return  # nothing more we can do with an unparseable refresh token

    if refresh_payload.type == "refresh":
        await blacklist_token(redis, refresh_payload.jti, refresh_payload.exp)
        result = await session.execute(select(RefreshToken).where(RefreshToken.jti == refresh_payload.jti))
        stored = result.scalars().first()
        if stored is not None:
            stored.revoked = True
            session.add(stored)
            await session.commit()
