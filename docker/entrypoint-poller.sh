#!/bin/sh
set -e

echo "Waiting for Postgres..."
until python -c "
import asyncio
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

echo "Waiting for the 'alerts' table to exist (i.e. api service has run migrations)..."
until python -c "
import asyncio
import asyncpg
from app.config import settings

async def check():
    conn_url = settings.database_url.replace('postgresql+asyncpg', 'postgresql')
    conn = await asyncpg.connect(conn_url)
    exists = await conn.fetchval(\"SELECT to_regclass('public.alerts')\")
    await conn.close()
    if not exists:
        raise SystemExit(1)

asyncio.run(check())
" 2>/dev/null; do
  sleep 1
done
echo "Schema is ready."

echo "Starting poller..."
exec python -m scripts.run_poller
