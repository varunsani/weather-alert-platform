"""Entrypoint for the standalone poller process. Run with: python -m scripts.run_poller"""

import asyncio

from app.services.poller import run_poller

if __name__ == "__main__":
    asyncio.run(run_poller())
