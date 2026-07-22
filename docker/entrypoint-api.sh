#!/bin/sh
set -e

echo "Waiting for Postgres..."
until python -c "
import asyncio, sys
import asyncpg
from app.config import settings

async def check():
    conn_url = settings.database_url.replace('postgresql+asyncpg', 'postgresql')
    conn = await asyncpg.connect(conn_url)
    await conn.close()

asyncio.run(check())
" 2>/dev/null; do
  sleep 1
done
echo "Postgres is up."

echo "Running Alembic migrations..."
alembic upgrade head

echo "Starting API server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
