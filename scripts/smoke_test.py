"""
End-to-end smoke test for the running stack (docker compose up first).

Run from the host machine (needs the api on :8000 and redis on :6379,
both exposed by docker-compose.yml):

    python3 scripts/smoke_test.py

Covers, in order:
  1. /health check
  2. Register + login a fresh test user
  3. Create a location + subscribe to it
  4. Connect the WebSocket and verify a manually-published Redis message
     is delivered live (this tests the whole pub/sub + connection-manager
     pipeline WITHOUT waiting on real severe weather)
  5. Logout, then confirm the old access token AND refresh token are
     both rejected (blacklist working)
  6. Login again with a fresh token pair
  7. Create a second location the user does NOT subscribe to, confirm:
       a) querying its current weather still works (on-demand query is
          decoupled from subscriptions)
       b) a Redis publish to that location's channel is NOT delivered to
          the socket (only subscribed locations get pushed to)
"""

import asyncio
import json
import os
import sys
import time

import httpx
import redis.asyncio as redis
import websockets

BASE_URL = os.environ.get("SMOKE_BASE_URL", "http://localhost:8000")
WS_BASE_URL = BASE_URL.replace("http://", "ws://").replace("https://", "wss://")
REDIS_URL = os.environ.get("SMOKE_REDIS_URL", "redis://localhost:6379/0")

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool, detail: str = "") -> None:
    status = PASS if condition else FAIL
    print(f"[{status}] {label}" + (f"  ({detail})" if detail else ""))
    if not condition:
        print("Aborting smoke test - fix the above before continuing.")
        sys.exit(1)


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        # ---------- 1. Health ----------
        r = await client.get("/health")
        check("GET /health", r.status_code == 200, r.text)

        # ---------- 2. Register + login ----------
        uname = f"smoketest_{int(time.time())}"
        password = "smoketestpass123"
        r = await client.post("/auth/register", json={
            "username": uname, "email": f"{uname}@example.com", "password": password
        })
        check("POST /auth/register", r.status_code == 201, r.text)

        r = await client.post("/auth/login", json={"username": uname, "password": password})
        check("POST /auth/login", r.status_code == 200, r.text)
        tokens = r.json()
        access_token, refresh_token = tokens["access_token"], tokens["refresh_token"]

        auth_headers = {"Authorization": f"Bearer {access_token}"}

        # ---------- 3. Create location + subscribe ----------
        r = await client.post("/locations", headers=auth_headers, json={
            "name": "Hyderabad", "latitude": 17.385, "longitude": 78.4867
        })
        check("POST /locations (subscribed location)", r.status_code == 201, r.text)
        loc_id = r.json()["id"]

        r = await client.post("/subscriptions", headers=auth_headers, json={"location_id": loc_id})
        check("POST /subscriptions", r.status_code == 201, r.text)

        # ---------- 4. WebSocket + Redis publish round-trip ----------
        ws_url = f"{WS_BASE_URL}/ws/alerts?token={access_token}"
        async with websockets.connect(ws_url) as ws:
            first_msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            check(
                "WebSocket 'connected' message lists the subscribed location",
                first_msg.get("type") == "connected" and loc_id in first_msg.get("location_ids", []),
                str(first_msg),
            )

            # Publish directly to Redis on this location's channel - this
            # simulates what the poller does when it classifies a severe
            # reading, without needing real severe weather to occur.
            r_client = redis.from_url(REDIS_URL, decode_responses=True)
            fake_alert = {
                "type": "alert", "location_id": loc_id, "location_name": "Hyderabad",
                "severity": "SEVERE", "condition_type": "EXTREME_HEAT",
                "message": "[smoke test] synthetic alert", "temperature_c": 45.0,
                "wind_speed_kmh": 10.0, "precipitation_mm": 0.0, "weather_code": 0,
                "created_at": "2026-01-01T00:00:00Z",
            }
            await r_client.publish(f"alerts.location.{loc_id}", json.dumps(fake_alert))
            await r_client.aclose()

            pushed = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            check(
                "Synthetic Redis publish delivered live over the WebSocket",
                pushed.get("message") == "[smoke test] synthetic alert",
                str(pushed),
            )

        # ---------- 5. Logout + blacklist verification ----------
        r = await client.post(
            "/auth/logout", headers=auth_headers, json={"refresh_token": refresh_token}
        )
        check("POST /auth/logout", r.status_code == 204, r.text)

        r = await client.get("/subscriptions", headers=auth_headers)
        check("Old access token rejected after logout", r.status_code == 401, r.text)

        r = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
        check("Old refresh token rejected after logout", r.status_code == 401, r.text)

        # ---------- 6. Login again ----------
        r = await client.post("/auth/login", json={"username": uname, "password": password})
        check("POST /auth/login (again, after logout)", r.status_code == 200, r.text)
        tokens = r.json()
        access_token = tokens["access_token"]
        auth_headers = {"Authorization": f"Bearer {access_token}"}

        # ---------- 7. Non-subscribed location ----------
        r = await client.post("/locations", headers=auth_headers, json={
            "name": "Reykjavik", "latitude": 64.13, "longitude": -21.82
        })
        check("POST /locations (second, NOT subscribed)", r.status_code == 201, r.text)
        other_loc_id = r.json()["id"]

        r = await client.get(f"/weather/{other_loc_id}/current", headers=auth_headers)
        check(
            "GET /weather/{id}/current works for a NON-subscribed location",
            r.status_code == 200,
            r.text,
        )

        ws_url = f"{WS_BASE_URL}/ws/alerts?token={access_token}"
        async with websockets.connect(ws_url) as ws:
            first_msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            # This user re-subscribed to nothing new; their only active
            # subscription from step 3 still stands, so `other_loc_id`
            # must NOT appear in this list.
            check(
                "Non-subscribed location is absent from the WebSocket registration",
                other_loc_id not in first_msg.get("location_ids", []),
                str(first_msg),
            )

            r_client = redis.from_url(REDIS_URL, decode_responses=True)
            await r_client.publish(f"alerts.location.{other_loc_id}", json.dumps({
                "type": "alert", "location_id": other_loc_id, "message": "should NOT arrive",
            }))
            await r_client.aclose()

            try:
                leaked = await asyncio.wait_for(ws.recv(), timeout=3)
                check("No alert leaked for the non-subscribed location", False, f"received: {leaked}")
            except asyncio.TimeoutError:
                check("No alert leaked for the non-subscribed location", True)

    print("\nAll smoke tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
