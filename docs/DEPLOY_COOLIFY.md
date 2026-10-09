# Deploy no Coolify (Git-based)

Guia para implantar o **OpenRouter Credit Monitor** pelo Coolify usando este
repositório Git. Um único processo = FastAPI + scheduler embutido + SQLite + UI.

> Nada de rede/domínio/volume/credenciais é presumido como existente. Siga a
> ordem **DEVELOP → STAGING → PRODUCTION** (production só com autorização explícita).

## 1. Pré-requisitos

- Coolify instalado e com acesso a este repositório privado (deploy key ou GitHub App).
- Evolution API já rodando e acessível na rede Docker do Coolify (host/porta internos).
- Uma chave de leitura de créditos da OpenRouter (`OPENROUTER_MANAGEMENT_KEY`).
- Hash de senha admin e `SESSION_SECRET` fortes (geração abaixo).

## 2. Tipo de recurso

Crie no Coolify um recurso **Docker Compose** (ou "Dockerfile") apontando para:

- Repositório: este repo
- Branch: `develop` (primeiro deploy), depois `staging`, por fim `production`
- Compose file: `docker-compose.yml` (contexto de build = raiz)
- Build: usa `backend/Dockerfile`

## 3. Porta / proxy reverso

- Porta interna: **`APP_PORT` (default 8080)**. O container escuta em
  `0.0.0.0:${APP_PORT}`. Não publique porta no host em produção.
- Configure o domínio/proxy do Coolify para encaminhar ao container na porta
  interna. Se servir sob prefixo (ex.: `/apps/openrouter-monitor`), defina
  `ROOT_PATH` igual ao prefixo e garanta que o proxy repassa o prefixo.
- Para servir na raiz do domínio, deixe `ROOT_PATH` vazio.

## 4. Secrets (Environment Variables no Coolify)

Defina como **variáveis/secrets do Coolify** (nunca no Git). Marque as sensíveis
como secret:

| Variável | Obrigatória | Observação |
|----------|-------------|------------|
| `APP_ENV` | sim | `production` (ativa o guard de segurança no boot) |
| `APP_PORT` | não | default `8080` |
| `ROOT_PATH` | condicional | prefixo do proxy, ou vazio |
| `OPENROUTER_MANAGEMENT_KEY` | sim | chave de créditos (secret) |
| `EVOLUTION_API_URL` | sim | ex.: `http://evolution-api:8080` (rede interna) |
| `EVOLUTION_API_KEY` | sim | secret |
| `EVOLUTION_INSTANCE` | sim | nome da instância |
| `WHATSAPP_DESTINATION` | sim | número com DDI, ex.: `5511...` |
| `AUTH_ENABLED` | sim | `true` (produção recusa `false`) |
| `ADMIN_USERNAME` | sim | ex.: `admin` |
| `ADMIN_PASSWORD_HASH` | sim | pbkdf2 (gerar abaixo) (secret) |
| `SESSION_SECRET` | sim | aleatório ≥32 chars (secret) |
| `COOKIE_SECURE` | recomendado | `true` quando HTTPS ponta a ponta |
| `DATABASE_URL` | não | default `sqlite:////app/data/monitor.db` |

> **Guard de produção:** com `APP_ENV=production`, o app **recusa subir** se
> `AUTH_ENABLED` não for true, `SESSION_SECRET` for fraco/default, ou
> `ADMIN_PASSWORD_HASH` for inválido. Isso é intencional (fail-fast).

Gerar segredos (local, com o venv do backend):

```bash
cd backend
python -m app.cli gen-secret                       # -> SESSION_SECRET
python -m app.cli hash-password 'sua-senha-forte'  # -> ADMIN_PASSWORD_HASH
```

## 5. Persistência (volume SQLite)

O compose usa um **volume nomeado** `monitor-data` montado em `/app/data`.
Isso preserva o `monitor.db` em restart/recreate/upgrade e mantém a escrita
funcionando sob usuário não-root (uid 10001). No Coolify, confirme que o volume
persistente está declarado e **não** é recriado a cada deploy.

## 6. Rede com a Evolution API

O container precisa alcançar a Evolution API pela rede interna do Docker. Aponte
`EVOLUTION_API_URL` para o nome de serviço/host interno (não para um domínio
público). Se a Evolution estiver em outro projeto compose, conecte este serviço
à rede externa compartilhada (ver bloco `networks` comentado no compose).

## 7. Healthcheck / readiness

- `GET /healthz` — liveness; **não** depende de OpenRouter/Evolution.
- `GET /readyz` — readiness; valida SQLite + schema + scheduler (503 se não pronto).
- O Dockerfile já define um `HEALTHCHECK` que consulta `/healthz` na `APP_PORT`.
  Configure o Coolify para usar `/healthz` como health path.

## 8. Logs

Logs vão para stdout/stderr (nível INFO). Não imprimem segredos (sem
Authorization, sem payloads completos). Diagnóstico: `MONITOR_STARTED`,
`BALANCE_CHECK`, `OPENROUTER_ERROR`, `WHATSAPP_ERROR`, etc.

## 9. Ordem de promoção

1. **DEVELOP** — deploy, validar boot, `/healthz`, `/readyz`, login, salvar
   limite, "Verificar agora", "Testar WhatsApp" com creds reais.
2. **STAGING** — repetir atrás do proxy real com `ROOT_PATH` definitivo.
3. **PRODUCTION** — **somente após autorização humana explícita**; exige
   integrações reais validadas e persistência comprovada.

## 10. Backup

Todo o estado é o arquivo SQLite no volume `monitor-data`.

```bash
# dentro do host, com o container parado ou em janela de baixa atividade:
docker run --rm -v monitor-data:/data -v "$PWD":/backup alpine \
  sh -c 'cp /data/monitor.db /backup/monitor-$(date +%F).db'
```

Guarde o `.db` em local seguro (fora do repositório). **Nunca** commite o `.db`.

## 11. Rollback

- **Código:** no Coolify, re-deploy do commit/tag anterior (ou `git revert` na
  branch e novo deploy). As branches `staging`/`production` permitem voltar a um
  estado conhecido sem reescrever histórico.
- **Dados:** restaure o `.db` do backup para o volume:

```bash
docker run --rm -v monitor-data:/data -v "$PWD":/backup alpine \
  sh -c 'cp /backup/monitor-AAAA-MM-DD.db /data/monitor.db'
```

Depois reinicie o container. Como `alert_triggered` é persistido, um saldo ainda
baixo **não** dispara alerta duplicado após o restart.
