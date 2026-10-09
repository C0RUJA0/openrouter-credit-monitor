# All-in-one stack: monitor + Evolution API (WhatsApp)

This brings up the monitor together with a self-hosted **Evolution API** (plus
its Postgres and Redis) so WhatsApp alerts work end-to-end on one host.

Evolution keeps a **persistent WhatsApp session** that you link by scanning a
**QR code** (like WhatsApp Web). That's why it's a separate service — it cannot
be embedded in the monitor's single container.

## 1. Configure secrets

```bash
cp .env.stack.example .env
# fill in: ADMIN_PASSWORD_HASH, SESSION_SECRET, OPENROUTER_MANAGEMENT_KEY,
#          EVOLUTION_API_KEY (strong random), POSTGRES_PASSWORD (strong random)
cd backend
python -m app.cli gen-secret            # SESSION_SECRET
python -m app.cli hash-password 'pw'    # ADMIN_PASSWORD_HASH
```

## 2. Bring up the stack

```bash
docker compose -f docker-compose.stack.yml up -d --build
```

Services: `openrouter-credit-monitor`, `evolution-api`, `evolution-postgres`,
`evolution-redis`. All data persists in named volumes.

## 3. Pair WhatsApp from the monitor (scan the QR)

Everything is done from the monitor — no need to touch Evolution directly. The
monitor already knows Evolution's internal URL/key/instance (from the stack env)
and creates the instance + shows the QR on demand.

1. Open the monitor, go to **Chaves & integrações**. The WhatsApp panel shows a
   **QR code** (generated live from Evolution).
2. On your phone: WhatsApp → **Aparelhos conectados** → **Conectar um aparelho**
   → scan the QR. The page auto-refreshes and switches to **WhatsApp conectado**
   once paired. The session persists (no re-scan unless you unlink).
3. Fill **WhatsApp — número de destino** with your number (e.g. `5511...`) and
   click **Salvar**, then **Testar** to confirm a message arrives.

The Evolution URL, API key and instance name come from the stack environment —
you never type them in the UI.

## 5. Security notes

- `EVOLUTION_API_KEY` and `POSTGRES_PASSWORD` are secrets — only in `.env`.
- Do not publish Evolution (`8088`) to the public internet; pairing/manager must
  stay on the LAN. Once paired, you can comment the `ports` block again.
- The monitor reaches Evolution over the internal Docker network, so no public
  port is needed for normal operation.

## 6. Backup

Back up all four volumes: `monitor-data`, `evolution-instances`,
`evolution-postgres`, `evolution-redis`. The WhatsApp session lives in
`evolution-instances` + Postgres; losing them means re-scanning the QR.
