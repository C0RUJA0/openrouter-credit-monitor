# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Implemented. Source split into `backend/` (Python service) and `frontend/` (server-rendered Jinja2 assets), each with its own `.env`. Full spec is `OPENROUTER_CREDIT_MONITOR_SPEC.md` (Portuguese) — still the source of truth for intent. Open items / things needing real-world validation live in `ERRORS_TODO.md`. This file summarizes the non-obvious decisions so you don't re-derive them.

## Layout & commands

- Backend package: `backend/app/` (`main.py` wiring + lifespan, `config.py`, `api/`, `services/`, `scheduler/`, `db/`). Tests: `backend/tests/`. Frontend: `frontend/templates/` + `frontend/static/`.
- `config.py` loads `backend/.env` then `frontend/.env` (real env always wins). `FRONTEND_DIR` resolves to the repo `frontend/` relative to the backend package.
- Install/dev: `cd backend && python -m venv .venv && .venv/Scripts/python.exe -m pip install -r requirements.txt`.
- Run: `cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8080` (single worker — scheduler is embedded).
- Tests: `cd backend && .venv/Scripts/python.exe -m pytest -q` (44 tests, all green). Single test: `pytest backend/tests/test_monitor.py::test_scenario_b_crossing_sends_once`.
- Password hash / session secret: `python -m app.cli hash-password '<pw>'`, `python -m app.cli gen-secret`.
- Docker (build context = repo root): `docker compose up --build -d`. Dockerfile at `backend/Dockerfile` copies both `backend/` and `frontend/`.

## What this builds

Self-hosted, single-container app that polls OpenRouter account credit balance and sends a WhatsApp alert (via Evolution API) when balance drops to/below a configurable threshold. Basic Jinja2 web UI for viewing balance, editing threshold, toggling notifications, manual check, and test message.

Stack (fixed by spec, do not add deps beyond this): Python 3.12, FastAPI, SQLAlchemy, SQLite, APScheduler, httpx, Jinja2, plain HTML/CSS, Docker.

**Explicitly forbidden** (spec §2, §34): AI/LLM, React/Next.js, Redis, PostgreSQL, Celery, RabbitMQ, extra microservices, own subdomain, scraping.

## Architecture

One container = FastAPI + embedded APScheduler + alert engine + SQLite + web UI. Evolution API is a separate external service reached over internal HTTP. Suggested layout in spec §23: `app/{api,services,scheduler,db,web}`, keeping these concerns strictly separated — OpenRouter integration, Evolution integration, monitoring logic, alert logic, database, web/UI, scheduler.

External API clients MUST be isolated in adapter modules (`services/openrouter.py`, `services/evolution.py`). The rest of the app must not depend on version-specific endpoint details — especially Evolution API, whose endpoint/body/auth shape varies by version and must be confirmed against the installed version before being fixed in code.

## Core invariants (where bugs hide — get these right)

- **Balance** = `total_credits - total_usage` from `GET https://openrouter.ai/api/v1/credits`. This is the account-global balance, NOT a per-API-key limit.
- **Money is `Decimal`**, never `float`. The comparison `balance <= threshold` must not suffer binary FP error.
- **Error ≠ zero balance.** Any OpenRouter failure (timeout, DNS, 401/403/429/5xx, bad JSON) → status `UNKNOWN/ERROR`, keep showing last known balance, never alert. Never `error → balance=0 → alert`.
- **Edge-triggered alerting, not level.** Alert fires only when `balance <= threshold` AND `alert_triggered == false`. On successful send set `alert_triggered = true`. No repeat while balance stays low. Re-arm (`alert_triggered = false`) only when balance rises back above threshold.
- **Send-confirmed state.** Only set `alert_triggered = true` after Evolution API confirms success. On send failure keep it `false`, log `WHATSAPP_ERROR`, retry with conservative backoff (immediate → +1min → +5min) — never a fast loop.
- **State is persisted, not in-memory.** `alert_triggered` lives in SQLite (`monitor_state`) so a restart with `balance < threshold` does NOT re-send. (Acceptance scenario H.)
- **Single check function** shared by scheduler and the "Verificar agora" button — no duplicated logic. Guard against concurrent checks with a lock; at most one alert per threshold-crossing cycle.
- **Threshold is NOT in `.env`.** Stored in SQLite `settings`, editable via UI, default 10.00 USD. Changing it re-evaluates current balance once (single alert if newly below; ensure re-armed if above).
- **`notifications_enabled == false`** still polls/updates UI/logs state, just skips WhatsApp send.

## Secrets

Secrets only in env vars: `OPENROUTER_MANAGEMENT_KEY`, `EVOLUTION_API_KEY`, admin creds. Never store in SQLite (incl. `metadata_json`), never show in UI, never return via endpoint, never log (no Authorization headers, no full error payloads that may contain secrets). Validate presence at startup without printing values. Password stored as hash (`ADMIN_PASSWORD_HASH`).

## Path prefix (mandatory, spec §12, §J)

App is served under `/apps/openrouter-monitor` behind the Central's reverse proxy — never assume mount at `/`. Use configurable `ROOT_PATH` env var (FastAPI `root_path`). CSS/JS assets, forms, redirects, internal links, endpoints, fetches must all work under the prefix. Listens internally on `0.0.0.0:8080`; no public port required in production (prefer Docker `expose` over `ports`).

## Persistence & scheduler

- SQLite at `/app/data/monitor.db`; `/app/data` is a Docker volume that survives restart/recreate/upgrade. Tables: `settings`, `monitor_state`, `events` (schemas in spec §14).
- Event types are enum/constants (spec §15): `BALANCE_CHECK`, `BALANCE_RECOVERED`, `ALERT_SENT`, `ALERT_REARMED`, `OPENROUTER_ERROR`, `WHATSAPP_TEST_SENT`, `WHATSAPP_ERROR`, `SETTINGS_CHANGED`, `MONITOR_STARTED`. Retention ~30 days / max rows, cleaned daily.
- **Single process / single worker** (scheduler embedded in the web process). Do not run multiple workers or scale horizontally without first coordinating/separating the scheduler.
- Every external HTTP call has explicit timeouts (connect 5s / read 10s), reusable client, limited conservative retry, no retry on 401/403.

## Endpoints (spec §24)

`GET /healthz` (process liveness — must NOT depend on OpenRouter/Evolution/WhatsApp), `GET /readyz` (SQLite + schema + scheduler + min config), `GET /`, `POST /settings`, `POST /actions/check-now`, `POST /actions/test-whatsapp`. Forms need CSRF; sessions use HttpOnly + SameSite cookies.

## Testing & completion bar

Use TDD for the critical logic: balance calc, threshold comparison, edge-trigger firing, anti-spam, re-arm, persistence across restart, send-failure handling, concurrency (two simultaneous checks must not double-send). Mock HTTP for OpenRouter and Evolution. **Done ≠ server starts** — must pass tests and demonstrate acceptance scenarios A–J (spec §31).

## Implementation notes

- Added deps beyond the spec's list, all core FastAPI ecosystem (no new frameworks): `uvicorn` (ASGI server), `python-multipart` (form parsing), `itsdangerous` (Starlette `SessionMiddleware`). Password hashing is stdlib `hashlib.pbkdf2_hmac` — no passlib/bcrypt.
- Money stored in SQLite as TEXT via `app/db/types.py:DecimalString` to keep exact `Decimal` (no FP). Datetimes are naive UTC (`models.utcnow`).
- Alert engine `app/services/alerts.py:evaluate` is pure (no DB/HTTP) and unit-tested. `app/services/monitor.py` orchestrates: non-blocking `threading.Lock`, send-failure backoff via `monitor_state.next_retry_at` / `alert_attempt_count`, `alert_triggered` persisted.
- External clients are injectable (`openrouter_client` / `evolution_client` args) so tests use `httpx.MockTransport` / fakes with no network.
- Auth: Starlette session cookie (HttpOnly, SameSite=lax, Secure gated by `COOKIE_SECURE`); CSRF token in session validated on every mutating POST. `AUTH_ENABLED=false` bypasses auth for local dev only.
