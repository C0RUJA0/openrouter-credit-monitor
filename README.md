# OpenRouter Credit Monitor

Self-hosted, single-container app that monitors the **account-global credit
balance** of an OpenRouter account and sends a WhatsApp alert (via Evolution
API) when the balance drops to or below a configurable threshold.

- No AI/LLM, no scraping, no external database. Python + FastAPI + SQLite.
- Server-rendered admin UI (Jinja2) with: current balance, integration status,
  editable threshold, notifications on/off, manual check, WhatsApp test, and a
  recent-events log.
- Designed to run **behind the Central reverse proxy** under a path prefix
  (e.g. `https://proartelab.com/apps/openrouter-monitor`). No own subdomain.

## 1. Architecture

```
OpenRouter ──HTTPS──▶ Credit Monitor (FastAPI + Scheduler + Alert Engine + SQLite + UI)
                              │ HTTP (internal)
                              ▼
                        Evolution API ──▶ WhatsApp
```

One container holds the backend, the embedded scheduler, the alert engine, the
SQLite DB, and the server-rendered UI. Evolution API is a **separate** external
service. The container needs no public port in production; the Central routes to
it over the shared Docker network.

Source layout (back and front split into their own folders, each with its own
`.env`):

```
.
├── backend/                 # Python service
│   ├── app/
│   │   ├── main.py          # app wiring + lifespan (startup/scheduler)
│   │   ├── config.py        # env-driven settings (+ loads backend/ & frontend/ .env)
│   │   ├── api/             # routers: health, auth, dashboard, settings, actions
│   │   ├── services/        # openrouter, evolution, alerts (pure), monitor
│   │   ├── scheduler/       # APScheduler jobs
│   │   └── db/              # models, database, migrations, repository
│   ├── tests/
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example         # SECRETS + core config
├── frontend/                # server-rendered UI assets
│   ├── templates/
│   ├── static/
│   └── .env.example         # presentation + ROOT_PATH (no secrets)
├── docker-compose.yml
└── data/                    # SQLite volume (created at runtime)
```

## 2. Requirements

- Docker + Docker Compose (production), or Python 3.11+ (local dev).
- An OpenRouter account and a **management/credits API key**.
- A running Evolution API instance with a connected WhatsApp session.

## 3. Credentials

- **OpenRouter key**: create a key in your OpenRouter account that can read the
  Credits API (`GET /api/v1/credits`). Put it in `OPENROUTER_MANAGEMENT_KEY`.
  The balance shown is `total_credits - total_usage` — the account's global
  balance, not a per-key limit.
- **Evolution API**: you need the base URL, API key, instance name, and the
  destination WhatsApp number (digits with country code, e.g. `55119...`).
- **Admin password hash** and **session secret**: see below.

## 4. Environment variables

Two files. Copy the examples and fill them in:

```bash
cp backend/.env.example  backend/.env
cp frontend/.env.example frontend/.env
```

`backend/.env` (secrets + core): `OPENROUTER_MANAGEMENT_KEY`, the `EVOLUTION_*`
+ `WHATSAPP_DESTINATION` values, `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH`,
`SESSION_SECRET`, `COOKIE_SECURE`, `DATABASE_URL`.

`frontend/.env` (presentation): `APP_TITLE`, `ROOT_PATH`.

Generate the admin hash and session secret:

```bash
# from backend/
python -m app.cli hash-password 'your-admin-password'   # -> ADMIN_PASSWORD_HASH
python -m app.cli gen-secret                             # -> SESSION_SECRET
```

> The **alert threshold is not an env var** — it lives in SQLite and is edited
> from the Web UI (default `10.00 USD` on first start).

## 5. Run locally (without Docker)

```bash
cd backend
python -m venv .venv && . .venv/Scripts/activate      # Windows Git Bash
# or: source .venv/bin/activate                        # Linux/macOS
pip install -r requirements.txt

# point the DB somewhere local and (optionally) disable auth for quick testing
export APP_ENV=development          # required: production refuses insecure auth/secret
export DATABASE_URL="sqlite:///./data/monitor.db"
export OPENROUTER_MANAGEMENT_KEY="..."
export AUTH_ENABLED=false          # dev convenience only (allowed in development)
export ROOT_PATH=""                # served at /

uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Open http://localhost:8080/ .

## 6. Run with Docker

```bash
# from project root (build context = root so both backend/ and frontend/ copy in)
docker compose up --build -d
docker compose logs -f
```

The compose file uses `expose` (no host port). For direct local access,
uncomment the `ports:` block in `docker-compose.yml`.

## 7. Connecting to Evolution API

Set `EVOLUTION_API_URL`, `EVOLUTION_API_KEY`, `EVOLUTION_INSTANCE`,
`WHATSAPP_DESTINATION` in `backend/.env`. The adapter targets Evolution API v2
by default:

- send text: `POST {url}/message/sendText/{instance}` with header `apikey`
- instance state: `GET {url}/instance/connectionState/{instance}`

If your Evolution version differs, adjust **only** `backend/app/services/evolution.py`.
Use the "Testar WhatsApp" button to validate the channel end-to-end.

## 8. ROOT_PATH / Central integration

Set `ROOT_PATH` in `frontend/.env` to the Central route (e.g.
`/apps/openrouter-monitor`). All UI URLs (assets, forms, redirects) are
generated relative to it, so the app works both at `/` and behind the prefix.
Point the Central's reverse proxy at the container's `:8080` on the shared
Docker network. Do **not** create a subdomain.

## 9. Tests

```bash
cd backend
pip install -r requirements.txt pytest pytest-asyncio
pytest -q
```

Covers the critical logic: balance calc (`Decimal`), the edge-triggered alert
engine, anti-spam / re-arm, send-failure backoff, persistence across restart,
threshold changes, and concurrency (two simultaneous checks → one alert).

## 10. Backup

The entire state is the single SQLite file:

```bash
cp ./data/monitor.db ./data/monitor-$(date +%F).db
```

Back up the `data/` directory. It survives container restart/recreate/upgrade
because it is a mounted volume.

## 11. Updating the container

```bash
git pull
docker compose build
docker compose up -d
```

The DB in `./data` persists across upgrades. On restart, a previously-sent
alert is **not** re-sent for a still-low balance (`alert_triggered` is persisted).

## 12. Troubleshooting

- **Balance shows "US$ --" / status UNKNOWN**: OpenRouter call failing — check
  `OPENROUTER_MANAGEMENT_KEY` and outbound network. An error never zeroes the
  balance or fires an alert; the last known balance is kept.
- **WhatsApp status not CONNECTED**: the Evolution instance isn't `open`. Open
  Evolution and reconnect the WhatsApp session.
- **No alert fired**: confirm notifications are ON, the balance actually crossed
  the threshold (edge-triggered — staying low won't re-fire), and the test
  message works.
- **Assets 404 behind the Central**: `ROOT_PATH` must match the Central route
  exactly, and the proxy must forward the prefix (or strip it consistently).
- **503 on `/readyz`**: DB/schema/scheduler not ready — check container logs.

## Scope

Single worker / single process (the scheduler is embedded). Do not scale the
container horizontally without first externalizing/coordinating the scheduler.

See `OPENROUTER_CREDIT_MONITOR_SPEC.md` for the full specification.
