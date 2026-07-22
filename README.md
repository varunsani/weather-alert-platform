# Weather Alert Platform

A real-time weather alerting platform: WebSocket-based live push delivery,
Redis Pub/Sub fan-out across independently polled location feeds, a
configurable severity-classification engine, JWT-authenticated location
subscriptions (access + refresh tokens, with Redis-backed blacklisting),
on-demand cached location queries, and PostgreSQL-backed time-series
persistence. Fully async throughout (FastAPI, SQLModel + asyncpg,
redis.asyncio).

---

## 1. Architecture

```
                                   ┌─────────────────────┐
                                   │   Open-Meteo API     │  (free, no key)
                                   └───────────▲──────────┘
                                               │ HTTP (polled)
                                   ┌───────────┴──────────┐
                                   │       poller          │  <- single process
                                   │ (app/services/poller) │     polls each UNIQUE
                                   └──────┬───────┬────────┘     subscribed location
                                          │       │               once per cycle
                          persists        │       │ publishes alert
                       WeatherReading,    │       │ (Redis Pub/Sub)
                          Alert rows      │       │
                                   ┌──────▼──┐ ┌──▼─────────────────┐
                                   │ Postgres│ │       Redis         │
                                   └────▲────┘ │ (blacklist / cache  │
                                        │      │  / pub-sub channel) │
                                        │      └──┬───────────┬──────┘
                              CRUD via  │         │ psubscribe│
                              SQLModel  │   ┌─────▼───┐  ┌────▼────┐
                                        │   │ api #1   │  │ api #2  │   <- horizontally
                                        └───┤ FastAPI  │  │ FastAPI │      scalable
                                            │ +WS      │  │ +WS     │
                                            └────┬─────┘  └────┬────┘
                                                 │ ws push       │ ws push
                                            ┌────▼────┐    ┌────▼────┐
                                            │ Client A │    │ Client B│
                                            └──────────┘    └─────────┘
```

**Why a separate poller service?** If polling lived inside every API
replica, N replicas would mean N redundant calls to Open-Meteo for the
same location, and duplicate DB rows. Instead, exactly one poller
process asks Postgres for the distinct set of locations that currently
have an active subscriber, polls each one exactly once, classifies
severity, persists the reading + any alerts, and **publishes** the
alert to a Redis Pub/Sub channel named `alerts.location.{id}`. Every API
replica subscribes to the wildcard pattern `alerts.location.*` once at
startup and forwards incoming messages only to the WebSocket clients
that are connected *to that replica* and *subscribed to that location*.
That's the fan-out.

## 2. Repository layout

```
weather-alert-platform/
├── app/
│   ├── main.py                  # FastAPI app, lifespan, router registration
│   ├── config.py                # pydantic-settings, reads .env
│   ├── database.py              # async SQLAlchemy engine + session dependency
│   ├── redis_client.py          # shared async Redis connection pool
│   ├── models/                  # SQLModel table definitions
│   │   ├── user.py, refresh_token.py, location.py,
│   │   └── subscription.py, weather_reading.py, alert.py
│   ├── schemas/                 # Pydantic request/response contracts
│   ├── auth/
│   │   ├── password.py          # bcrypt hashing
│   │   ├── jwt_handler.py        # access + refresh token create/decode
│   │   ├── blacklist.py          # Redis-backed token revocation
│   │   └── dependencies.py       # get_current_user (HTTP) / get_current_user_ws
│   ├── routers/
│   │   ├── auth.py               # register / login / refresh / logout
│   │   ├── locations.py          # create/list polled locations
│   │   ├── subscriptions.py      # subscribe / unsubscribe / list
│   │   ├── weather.py            # cached current query + history
│   │   └── ws.py                 # /ws/alerts live push endpoint
│   ├── services/
│   │   ├── weather_client.py     # Open-Meteo async HTTP client
│   │   ├── severity_engine.py    # ALL tunable thresholds live here
│   │   ├── poller.py              # the standalone polling loop
│   │   ├── pubsub.py              # publish (poller) + forward (api) via Redis
│   │   └── connection_manager.py  # per-instance in-memory WS registry
│   ├── core/exceptions.py        # global exception handlers
│   └── static/test_client.html   # zero-dependency browser test client
├── alembic/                      # migrations (hand-written initial schema)
├── scripts/run_poller.py         # poller process entrypoint
├── docker/                       # entrypoint shell scripts for containers
├── Dockerfile
├── docker-compose.yml            # postgres + redis + api + poller
├── requirements.txt
├── .env.example
└── README.md
```

## 3. Prerequisites

- Docker + Docker Compose (recommended path — everything below assumes this)
- OR: Python 3.12+, a local PostgreSQL 16 and Redis 7, if you'd rather run
  it without Docker
- Git
- A free GitHub account (to push the repo, since we're using your own new repo)

## 4. First-time setup (from absolute zero)

### Step 1 — Get the code onto your machine
You already have the generated project folder. Open a terminal inside it:
```bash
cd weather-alert-platform
```

### Step 2 — Create your local environment file
```bash
cp .env.example .env
```
Open `.env` and replace `JWT_SECRET_KEY` with a real random secret:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```
Paste the output as the value of `JWT_SECRET_KEY` in `.env`.
Everything else in `.env.example` already matches the Docker Compose
service names (`postgres`, `redis`) and works out of the box.

### Step 3 — Build and start everything
```bash
docker compose up --build
```
This starts, in order:
1. `postgres` (with a healthcheck so nothing else starts before it's ready)
2. `redis` (same)
3. `api` — waits for both, runs `alembic upgrade head` to create every
   table, then starts `uvicorn` on port 8000
4. `poller` — waits for Postgres, Redis, *and* for the `alerts` table to
   exist (i.e. api's migration has run), then starts its polling loop

You should see logs like:
```
weather_api      | INFO:     Uvicorn running on http://0.0.0.0:8000
weather_poller   | INFO:poller:Poller starting. Interval=300s
```

### Step 4 — Open the test client
Go to **http://localhost:8000/static/test_client.html** in a browser.
Also available: interactive API docs at **http://localhost:8000/docs**.

### Step 5 — Walk through the flow
In the test client (or via `curl`/Postman using `/docs`):
1. **Register** a user, then **Login** — this stores an access + refresh
   token in the page.
2. **Create/Get Location** — e.g. name "Hyderabad", lat `17.385`, lon
   `78.4867`. Coordinates are rounded to 2 decimals (~1.1km) so nearby
   requests reuse the same polled location instead of creating duplicates.
3. **Subscribe** to that location.
4. **Connect WebSocket** — opens `/ws/alerts?token=<access_token>`. You'll
   get a `"connected"` confirmation listing which location_ids you're
   registered for.
5. Wait for the poller's next cycle (default every 300s, configurable via
   `POLL_INTERVAL_SECONDS` in `.env` — set it to something like `30` while
   testing so you don't have to wait 5 minutes). If the classified
   severity for that location crosses any threshold, you'll see an
   `ALERT PUSH` message appear live in the log, with no page refresh.
6. Try **Query Current Weather** any time — this hits the cached
   on-demand endpoint (`/weather/{id}/current`), which only calls
   Open-Meteo directly if the 5-minute Redis cache has expired.

### Step 6 — See real fan-out across multiple instances (optional)
```bash
docker compose up --build --scale api=1   # already the default
```
To actually witness cross-instance fan-out: run a second api container by
hand on a different port (`docker run` with the same image/env pointing
at the same Postgres/Redis, mapped to e.g. `8001:8000`), connect one
browser tab's WebSocket to `:8000` and another to `:8001` with the same
subscribed location — both will receive the same poller-published alert,
proving delivery goes through Redis, not direct process memory.

## 5. Running without Docker (local Python)

```bash
python3 -m venv venv
source venv/bin/activate           # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                # then edit DATABASE_URL(_SYNC) and REDIS_URL
                                     # to point at your local Postgres/Redis,
                                     # and set a real JWT_SECRET_KEY

alembic upgrade head                 # create all tables

# terminal 1
python -m uvicorn app.main:app --reload

# terminal 2
python -m scripts.run_poller
```

## 6. Database migrations (Alembic)

The initial migration (`alembic/versions/0001_initial.py`) is
hand-written to precisely match every SQLModel table. If you add or
change a model afterwards:
```bash
alembic revision --autogenerate -m "describe your change"
alembic upgrade head
```
Always review autogenerated migrations before applying them — autogenerate
is a helpful diff, not a guarantee.

## 7. API reference (summary)

All endpoints except `/auth/*` and `/health` require
`Authorization: Bearer <access_token>`.

| Method | Path                          | Purpose                                   |
|--------|-------------------------------|--------------------------------------------|
| POST   | `/auth/register`              | Create a user                              |
| POST   | `/auth/login`                 | Get access + refresh token pair            |
| POST   | `/auth/refresh`                | Exchange a valid refresh token for a new access token |
| POST   | `/auth/logout`                 | Blacklist current access + refresh tokens  |
| POST   | `/locations`                   | Create or fetch an existing polled location|
| GET    | `/locations`                   | List all known locations                   |
| GET    | `/locations/{id}`              | Get one location                           |
| POST   | `/subscriptions`               | Subscribe to a location                    |
| GET    | `/subscriptions`                | List your active subscriptions            |
| DELETE | `/subscriptions/{location_id}` | Unsubscribe                                |
| GET    | `/weather/{id}/current`         | Cached on-demand current weather           |
| GET    | `/weather/{id}/history?limit=` | Persisted time-series readings             |
| WS     | `/ws/alerts?token=`             | Live alert push for your subscriptions     |

Full interactive schema: `/docs` (Swagger UI) or `/redoc`.

## 8. Severity engine — how it decides what's "severe"

Every threshold lives in **`app/services/severity_engine.py`** in two
plain dicts (`SEVERITY_RULES`, `WEATHER_CODE_SEVERITY`) — nothing else in
the codebase needs to change to retune sensitivity:

- **Extreme heat / cold** — three tiers each (`WATCH` → `WARNING` →
  `SEVERE`) based on °C thresholds.
- **High wind** — three tiers based on km/h.
- **Heavy precipitation** — three tiers based on mm/hour.
- **Severe weather codes** — Open-Meteo returns a WMO weather code (fog,
  drizzle, rain, snow, thunderstorm, hail, etc.); each code is mapped
  directly to a severity tier (e.g. plain fog is a `WATCH`, hail-bearing
  thunderstorms are `SEVERE`).

For one weather reading, each of the four categories independently
produces **at most one** alert, at the highest tier it crosses — so a
single violent thunderstorm reading won't spam five overlapping alerts
for the same underlying event.

## 9. JWT auth design

- **Access token**: 15 minutes, used for all HTTP + WebSocket auth.
- **Refresh token**: 7 days, tracked in Postgres (`refresh_tokens` table)
  so a specific session can be identified/revoked, not just blacklisted.
- **Blacklisting**: both token types carry a unique `jti`. On logout,
  the presented tokens' `jti`s are written to Redis with a TTL equal to
  their remaining lifetime — so the blacklist entry expires exactly when
  the token would have anyway, with no manual cleanup needed.
- **WebSocket auth**: the access token is passed as `?token=` on the
  connect URL (browsers can't set custom headers during the WS
  handshake). Same validation + blacklist check as HTTP.

## 10. Git & GitHub — from zero

Inside the project folder:
```bash
git init
git add .
git commit -m "Initial commit: real-time weather alert platform"
```

Create a **new, empty** repository on GitHub (no README/license/gitignore —
those already exist locally), then:
```bash
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo-name>.git
git push -u origin main
```

If you use SSH instead of HTTPS:
```bash
git remote add origin git@github.com:<your-username>/<your-repo-name>.git
git push -u origin main
```

`.env` is already gitignored — never commit real secrets. Anyone cloning
the repo starts from `.env.example` as documented in Step 2 above.

## 11. A note on the free weather API

Open-Meteo's free tier requires no API key and has a generous rate limit
for non-commercial use, which is exactly why the poller design polls each
unique location once per cycle rather than once per subscriber — it's
respectful of the upstream free tier by construction, not just by luck.
