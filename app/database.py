"""
Async database engine + session management.

Uses SQLAlchemy's async engine (via asyncpg) with SQLModel models.
A single AsyncSession is handed out per request via FastAPI's Depends()
and is always closed afterwards, whether the request succeeded or failed.
"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=(settings.environment == "development"),
    pool_pre_ping=True,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a DB session per-request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
