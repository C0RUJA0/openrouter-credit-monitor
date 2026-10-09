# WhatsApp — pairing from the app

The default deployment (`docker-compose.yml`) is **all-in-one**: it brings up the
monitor together with a bundled **Evolution API** (plus its Postgres + Redis).
Everything is wired automatically — the monitor talks to Evolution over the
internal network and shows the **pairing QR in its own UI**. You never deploy or
configure Evolution separately.

## Deploy

```bash
docker compose up -d --build
```

That's it. Four services come up: `openrouter-credit-monitor`, `evolution-api`,
`evolution-postgres`, `evolution-redis`. For local/LAN it needs **no `.env`** —
it boots with safe defaults.

## Pair your WhatsApp (scan the QR in the monitor)

1. Open the monitor → **Chaves & integrações**. The WhatsApp panel shows a
   **QR code** (generated live from the bundled Evolution).
2. On your phone: WhatsApp → **Aparelhos conectados** → **Conectar um aparelho**
   → scan it. The page auto-refreshes and switches to **WhatsApp conectado** once
   paired. The session persists (no re-scan unless you unlink).
3. Fill **WhatsApp — destinos** and **Salvar**, then **Testar** to confirm.

## Destinations (one or many)

The destinations box accepts **multiple targets**, one per line (or comma-
separated):

- phone numbers with country code — e.g. `5511999990000`
- WhatsApp group IDs — e.g. `120363000000000000@g.us`

Alerts and the test message are sent to **every** target listed.

> Finding a group ID: send from the group once, or use Evolution's
> `GET /group/fetchAllGroups` endpoint. (Optional: expose the Evolution manager
> by uncommenting the `ports: - "8088:8080"` block for `evolution-api`.)

## Production hardening

For a public/production deploy, override via environment (or Coolify secrets):

| Variable | Why |
|----------|-----|
| `APP_ENV=production` | enables the startup security guard |
| `ADMIN_PASSWORD_HASH`, `SESSION_SECRET` | required admin auth + session signing |
| `OPENROUTER_MANAGEMENT_KEY` | real balance (also settable in the UI) |
| `EVOLUTION_API_KEY` | strong value (replaces the dev default) |
| `POSTGRES_PASSWORD` | strong value (replaces the dev default) |
| `LAN_ONLY=true` | restrict access to the home/LAN network |

Generate monitor secrets:

```bash
cd backend
python -m app.cli gen-secret            # SESSION_SECRET
python -m app.cli hash-password 'pw'    # ADMIN_PASSWORD_HASH
```

## Backup

Back up the named volumes: `monitor-data` (app DB), `evolution-instances` +
`evolution-postgres` (WhatsApp session — losing these means re-scanning the QR),
and `evolution-redis`.

## Monitor-only

If you already run Evolution elsewhere (or deploy behind the Central proxy with
no bundled WhatsApp), use `docker-compose.monitor-only.yml` instead and set the
`EVOLUTION_*` env vars to point at your existing instance.
