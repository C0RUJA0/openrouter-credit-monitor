# ERRORS_TODO — pendências para resolver depois

Nenhum erro bloqueante. Suíte de testes: **44 passando**. App sobe, lifespan OK,
endpoints OK, path prefix OK. Os itens abaixo são validações que dependem de
ambiente real (rede/serviços externos/Docker) e não puderam ser confirmados
nesta máquina. Tratar como tasks.

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
