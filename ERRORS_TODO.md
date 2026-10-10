# ERRORS_TODO — pendências para resolver depois

Nenhum erro bloqueante. Suíte de testes: **55 passando**. App sobe, lifespan OK,
endpoints OK, path prefix OK. Os itens abaixo são validações que dependem de
ambiente real (rede/serviços externos/Docker) e não puderam ser confirmados
nesta máquina. Tratar como tasks.

## Resolvido (hardening Fase 2)
- Guard de produção: `APP_ENV=production` recusa subir com auth desabilitada,
  `SESSION_SECRET` fraco/default ou `ADMIN_PASSWORD_HASH` inválido
  (`config.py:validate_runtime`, testes em `test_config_guard.py`).
- Porta interna configurável via `APP_PORT` (Dockerfile honra `${APP_PORT}`).
- Build mais reproduzível: deps diretas pinadas (`==`) + base `bookworm`.
- Persistência SQLite via **volume nomeado** (escrita OK sob não-root).
- `.dockerignore` reforçado (sem `tests/`, `.env.example`, `*.md`).
- `/readyz` usa `scheduler.running` público (sem acesso a atributo privado).
- Smoke test de boot real (`test_app_smoke.py`): `/healthz`, `/readyz`, `/`, static.

## Pendências que exigem ambiente externo (BLOQUEIOS)
- **Docker não disponível nesta máquina** → `docker build`/compose, healthcheck
  real, volume e lock transitivo (`pip freeze` dentro da imagem 3.12) não
  validados. Rodar `docker compose up --build -d` onde houver Docker.
- **Publicação GitHub** → `gh` logado aqui é conta diferente da do projeto;
  precisa de autorização explícita e destino do repositório antes do push.

## 1. Confirmar contrato real da OpenRouter Credits API
- **O quê:** o adapter assume resposta `{"data": {"total_credits": X, "total_usage": Y}}`
  em `GET /api/v1/credits`, com `balance = total_credits - total_usage`.
- **Risco:** se o formato atual diferir, `get_credits()` levanta `OpenRouterError`
  (status UNKNOWN, sem falso zero — seguro), mas não lê o saldo.
- **Ação:** chamar a API com uma key real, conferir o JSON, ajustar só
  `backend/app/services/openrouter.py` se preciso. Adicionar teste com o payload real.

## 2. Confirmar versão/endpoints da Evolution API
- **O quê:** adapter mira Evolution v2: envio `POST /message/sendText/{instance}`
  (header `apikey`, body `{"number","text"}`) e estado
  `GET /instance/connectionState/{instance}` (`state == "open"` = conectado).
- **Risco:** versões diferentes mudam rota/body/header de auth.
- **Ação:** confirmar contra a versão instalada; ajustar só
  `backend/app/services/evolution.py`. Validar ponta-a-ponta pelo botão
  "Testar WhatsApp".

## 3. Build/execução Docker não validada aqui
- **O quê:** `docker` não está disponível neste ambiente; `Dockerfile` e
  `docker-compose.yml` foram escritos mas não buildados.
- **Ação:** `docker compose up --build -d` na raiz; conferir healthcheck
  (`/healthz`), volume `./data` persistindo o `monitor.db`, usuário não-root.

## 4. Integração real atrás da Central (cenário J)
- **O quê:** `ROOT_PATH` verificado via TestClient (assets/forms/redirects saem
  prefixados). Falta validar com o reverse proxy real da Central encaminhando
  `/apps/openrouter-monitor`.
- **Ação:** publicar atrás da Central, carregar a página, testar login, salvar
  limite, "Verificar agora" e "Testar WhatsApp" pelo domínio público.

## 5. Fuso horário na UI
- **O quê:** timestamps gravados/exibidos em UTC naive. A UI mostra UTC, não
  horário local (ex.: "02/10/2026 16:45" no spec presume local).
- **Ação (opcional):** converter para America/Sao_Paulo na camada de
  apresentação (`app/web_view.py`) se o operador quiser horário local.

## 6. Reschedule do intervalo via UI
- **O quê:** campo de intervalo existe no backend (mín. 60s) e o form envia o
  valor atual num hidden; não há input editável de intervalo na UI (v1 prioriza
  o limite monetário, conforme spec §28).
- **Ação (opcional):** expor input de intervalo no template se desejado.

## 7. Validar contrato do findMessages (anti-spam de grupo)
- **O quê:** `last_message_is_from_me()` usa `POST /chat/findMessages/{instance}`
  com `{"where":{"key":{"remoteJid":jid}}}` e lê `records[].key.fromMe` +
  `messageTimestamp`. Shape pode variar por versão da Evolution.
- **Risco:** se o shape diferir, retorna None → fail-open (envia mesmo assim),
  nunca suprime alerta por engano. Seguro, mas o anti-spam pode não ativar.
- **Ação:** conferir o JSON real contra a Evolution instalada (v2.3.7) e ajustar
  só o parse em `backend/app/services/evolution.py` se preciso.
