# OpenRouter Credit Monitor — Especificação de Implementação

## 1. Objetivo

Criar um app simples, self-hosted e containerizado para monitorar o saldo de créditos da conta OpenRouter e enviar um alerta via WhatsApp usando Evolution API quando o saldo ficar menor ou igual a um limite configurável.

O app deve possuir uma interface web básica para:

- visualizar o saldo atual da OpenRouter;
- visualizar o estado da última verificação;
- alterar o valor do limite de alerta;
- ativar/desativar notificações;
- executar uma verificação manual;
- enviar uma mensagem de teste via WhatsApp;
- visualizar o estado básico da integração com a Evolution API;
- visualizar os eventos recentes do monitor.

O app será integrado à Central de Apps existente.

**Não criar subdomínio próprio.**

O acesso público deve acontecer exclusivamente através do domínio principal:

```text
https://proartelab.com
```

por uma rota interna da Central, preferencialmente:

```text
/apps/openrouter-monitor
```

O container do app não deve depender de exposição pública direta.

---

# 2. Princípios de arquitetura

Manter o projeto pequeno, conservador e fácil de manter.

Não adicionar:

- IA;
- LLM;
- React;
- Next.js;
- Redis;
- PostgreSQL;
- Celery;
- RabbitMQ;
- microserviços desnecessários.

Stack preferida:

- Python 3.12
- FastAPI
- SQLAlchemy
- SQLite
- APScheduler
- httpx
- Jinja2
- HTML/CSS simples
- Docker

Um único container deve conter:

- backend;
- interface web;
- scheduler;
- engine de alertas.

A Evolution API permanece como serviço separado.

Arquitetura:

```text
                         OpenRouter
                             |
                             | HTTPS
                             v
                 +-------------------------+
                 | openrouter-credit-      |
                 | monitor                 |
                 |                         |
                 | FastAPI                 |
                 | Scheduler               |
                 | Alert Engine            |
                 | SQLite                  |
                 | Web UI                  |
                 +------------+------------+
                              |
                              | HTTP interno
                              v
                     +----------------+
                     | Evolution API  |
                     +--------+-------+
                              |
                              v
                           WhatsApp
```

A interface pública deve ser alcançada assim:

```text
Usuário
  |
  v
https://proartelab.com
  |
  v
Central de Apps
  |
  v
/apps/openrouter-monitor
  |
  v
openrouter-credit-monitor:8080
```

Não criar:

```text
credits.proartelab.com
openrouter.proartelab.com
monitor.proartelab.com
```

ou qualquer outro subdomínio para este app.

---

# 3. OpenRouter

## 3.1 Fonte de dados

Não fazer scraping do site da OpenRouter.

Usar a API oficial de créditos.

Referência oficial atual:

```text
GET https://openrouter.ai/api/v1/credits
```

A OpenRouter documenta a Credits API como a forma de consultar saldo/créditos restantes.

O cliente deve ficar isolado em um módulo próprio.

Exemplo de responsabilidade:

```text
OpenRouterClient
    |
    +-- consulta endpoint
    +-- valida HTTP status
    +-- valida JSON
    +-- extrai total_credits
    +-- extrai total_usage
    +-- calcula balance
```

O saldo deve ser calculado como:

```text
balance = total_credits - total_usage
```

Não confundir essa informação com limites de uma API key individual.

O objetivo deste app é monitorar o saldo global disponível da conta.

## 3.2 Autenticação

A credencial da OpenRouter deve ficar somente em variável de ambiente/secret.

Exemplo:

```env
OPENROUTER_MANAGEMENT_KEY=...
```

Nunca:

- armazenar a chave no SQLite;
- mostrar a chave na interface;
- devolver a chave por endpoint;
- registrar a chave em logs;
- incluir a chave em mensagens de erro.

A implementação deve validar no startup que a credencial necessária existe, sem imprimir seu conteúdo.

## 3.3 Erros

Falha ao consultar a OpenRouter NÃO significa saldo zero.

Em caso de:

- timeout;
- DNS error;
- HTTP 401;
- HTTP 403;
- HTTP 429;
- HTTP 5xx;
- JSON inválido;
- resposta inesperada;

o estado deve ser:

```text
UNKNOWN / ERROR
```

e o último saldo válido deve continuar sendo apresentado como:

```text
Último saldo conhecido
```

Nunca executar:

```text
erro de API
-> saldo = 0
-> disparar alerta de créditos
```

---

# 4. Frequência de verificação

Valor padrão:

```text
300 segundos
```

ou seja:

```text
5 minutos
```

O scheduler deve rodar dentro do próprio processo/aplicação de forma previsível.

A função usada pelo scheduler e pelo botão "Verificar agora" deve ser a mesma.

Não duplicar lógica.

Fluxo:

```text
check_balance()
    |
    +-- consulta OpenRouter
    +-- valida resultado
    +-- atualiza estado
    +-- avalia regra de alerta
    +-- persiste evento
```

Evitar verificações concorrentes.

Se uma verificação ainda estiver em andamento, uma nova execução não deve iniciar outra consulta concorrente.

Implementar lock simples ou equivalente.

---

# 5. Regra de alerta

## 5.1 Limite padrão

Valor inicial:

```text
US$ 10.00
```

Porém o valor NÃO deve ser fixo no código.

Ele deve ser armazenado no SQLite e editável pela Web UI.

Exemplo:

```text
alert_threshold = 10.00
```

## 5.2 Condição

Enviar alerta quando:

```text
balance <= alert_threshold
```

e:

```text
alert_triggered == false
```

Depois que o envio for concluído com sucesso:

```text
alert_triggered = true
```

Não continuar enviando mensagens enquanto o saldo permanecer abaixo do limite.

Exemplo:

```text
US$ 15.00 -> nada
US$ 11.20 -> nada
US$ 10.40 -> nada
US$ 9.95  -> ALERTA
US$ 9.20  -> nada
US$ 7.00  -> nada
US$ 3.00  -> nada
```

O comportamento deve ser baseado em cruzamento/estado, não em repetição contínua da condição.

---

# 6. Rearme automático

Depois de um alerta ter sido enviado, o monitor deve ser rearmado quando o saldo voltar a ficar acima do limite.

Exemplo:

```text
threshold = US$ 10

saldo US$ 9.50
-> alerta enviado
-> alert_triggered = true

saldo US$ 8.00
-> nada

usuário recarrega créditos

saldo US$ 35.00
-> alert_triggered = false
-> monitor rearmado

posteriormente:

saldo US$ 9.90
-> novo alerta
```

Registrar um evento de recuperação/rearme.

---

# 7. Alteração do limite pela Web UI

Ao alterar o limite, a aplicação deve salvar imediatamente o novo valor no SQLite.

Exemplo:

```text
US$ 10.00 -> US$ 15.00
```

A alteração do limite precisa ser tratada de forma consistente com o estado atual.

Regra recomendada:

- salvar o novo limite;
- reavaliar imediatamente o saldo conhecido mais recente;
- não gerar spam;
- se o novo limite colocar o saldo atual em estado de alerta e não houver alerta ativo correspondente, permitir um único alerta;
- se o saldo estiver acima do novo limite, garantir que o monitor esteja rearmado.

Registrar:

```text
SETTINGS_CHANGED
```

com:

- valor anterior;
- valor novo;
- timestamp.

---

# 8. Evolution API

## 8.1 Objetivo

A Evolution API será somente o canal de envio das mensagens.

O monitor NÃO deve gerenciar diretamente sessão do WhatsApp Web.

Fluxo:

```text
Monitor
  |
  | HTTP
  v
Evolution API
  |
  v
WhatsApp
```

## 8.2 Configuração

Usar variáveis de ambiente para:

```env
EVOLUTION_API_URL=http://evolution-api:8080
EVOLUTION_API_KEY=...
EVOLUTION_INSTANCE=openrouter-monitor
WHATSAPP_DESTINATION=55XXXXXXXXXXX
```

Esses dados não devem ficar editáveis inicialmente pela Web UI.

A Web UI pode apenas mostrar status sanitizado, como:

```text
Evolution API: conectada
Instância: openrouter-monitor
Destino: ********1234
```

Nunca mostrar a API key.

## 8.3 Compatibilidade

A Evolution API possui versões diferentes.

Não assumir silenciosamente um formato de endpoint sem verificar a versão efetivamente instalada.

Criar um adapter:

```text
EvolutionClient
```

responsável por:

- montar a URL;
- autenticar;
- consultar estado da instância, quando suportado;
- enviar texto;
- tratar erros;
- aplicar timeout.

Antes de finalizar a implementação, confirmar na documentação da versão instalada da Evolution API:

- endpoint de envio de texto;
- formato do body;
- header de autenticação;
- endpoint/status da instância.

Isolar qualquer diferença de versão exclusivamente nesse adapter.

O restante do app não deve depender de detalhes específicos da versão da Evolution API.

## 8.4 Falha no envio

Um ponto importante:

```text
saldo <= limite
```

não significa que:

```text
alert_triggered = true
```

automaticamente.

Somente marcar o alerta como enviado após confirmação de sucesso da Evolution API.

Em caso de falha:

```text
alert_triggered = false
```

e registrar:

```text
WHATSAPP_ERROR
```

Porém também não gerar spam de tentativas.

Implementar retry com backoff conservador.

Sugestão inicial:

```text
tentativa 1: imediata
tentativa 2: +1 minuto
tentativa 3: +5 minutos
```

Depois disso, deixar o scheduler normal tentar novamente em verificações futuras, mas limitar frequência de novas tentativas.

Nunca criar um loop rápido.

---

# 9. Mensagem de alerta

Formato básico:

```text
🚨 OpenRouter — Créditos baixos

Seu saldo chegou ao limite configurado.

Saldo atual: US$ 9,87
Limite: US$ 10,00
```

Valores monetários devem ser formatados com duas casas decimais.

Não incluir:

- Management Key;
- API keys;
- URLs internas;
- stack trace;
- informações sensíveis.

---

# 10. Mensagem de teste

A interface deve possuir:

```text
[ Testar WhatsApp ]
```

Ao clicar:

- enviar mensagem via Evolution API;
- não alterar `alert_triggered`;
- registrar `WHATSAPP_TEST_SENT` em caso de sucesso;
- registrar `WHATSAPP_ERROR` em caso de erro.

Mensagem:

```text
✅ OpenRouter Credit Monitor

Mensagem de teste enviada com sucesso.
```

A UI deve apresentar feedback claro.

---

# 11. Interface Web

Criar uma interface administrativa simples e responsiva.

Não é necessário framework SPA.

Preferir Jinja2 + HTML/CSS.

Tela principal:

```text
+------------------------------------------------+
| OpenRouter Credit Monitor                      |
+------------------------------------------------+
|                                                |
| Saldo atual                                    |
| US$ 32,47                                      |
|                                                |
| 🟢 Normal                                      |
|                                                |
+------------------------------------------------+
| ALERTA                                         |
|                                                |
| Avisar quando o saldo chegar a:                |
|                                                |
| US$ [ 10.00 ]                                  |
|                                                |
| [ Salvar ]                                     |
|                                                |
| Notificações [ ON ]                            |
+------------------------------------------------+
| OpenRouter        🟢 Online                    |
| WhatsApp          🟢 Conectado                 |
|                                                |
| Última consulta   02/10/2026 16:45             |
| Último alerta     —                            |
|                                                |
| [ Verificar agora ]                            |
| [ Testar WhatsApp ]                            |
+------------------------------------------------+
| Eventos recentes                               |
|                                                |
| 16:45 Saldo atualizado        US$ 32.47        |
| 16:40 Saldo atualizado        US$ 32.51        |
+------------------------------------------------+
```

Status possíveis:

### Saldo

```text
NORMAL
LOW
UNKNOWN
```

### OpenRouter

```text
ONLINE
ERROR
UNKNOWN
```

### WhatsApp/Evolution

```text
CONNECTED
DISCONNECTED
ERROR
UNKNOWN
```

Evitar afirmar "Conectado" apenas porque a Evolution API respondeu HTTP 200.

Usar, quando disponível, o estado real da instância.

---

# 12. Aplicação atrás de path prefix

Este requisito é obrigatório.

O app será servido por uma rota da Central, por exemplo:

```text
/apps/openrouter-monitor
```

Portanto a aplicação deve suportar corretamente execução atrás de reverse proxy/path prefix.

Não assumir que está sempre montada em:

```text
/
```

Garantir que:

- assets CSS/JS;
- forms;
- redirects;
- links internos;
- endpoints;
- fetches;

continuem funcionando quando publicada abaixo de:

```text
/apps/openrouter-monitor
```

Preferir suporte configurável:

```env
ROOT_PATH=/apps/openrouter-monitor
```

ou mecanismo equivalente do FastAPI/Starlette.

Internamente, o serviço pode continuar ouvindo:

```text
0.0.0.0:8080
```

mas não deve exigir porta pública na internet.

---

# 13. Segurança da interface

A aplicação deve ter autenticação administrativa simples.

Não expor o painel anonimamente.

Pode ser implementada inicialmente com:

```env
ADMIN_USERNAME=...
ADMIN_PASSWORD_HASH=...
```

ou solução equivalente segura.

Preferir armazenar hash da senha em vez de senha plaintext.

Caso a autenticação da Central já seja responsável por proteger completamente a rota no ambiente final, manter a autenticação local como camada opcional/configurável, sem quebrar a integração.

Adicionar proteção adequada para alterações de configuração e ações POST.

No mínimo:

- sessão segura;
- cookies `HttpOnly`;
- `SameSite`;
- CSRF para forms mutáveis ou mecanismo equivalente;
- nenhum segredo enviado para o browser.

Não implementar "login fake" somente no frontend.

---

# 14. SQLite

Persistência em:

```text
/app/data/monitor.db
```

Montar `/app/data` como volume Docker.

Banco deve sobreviver a:

- restart;
- recreate;
- upgrade do container.

Tabelas sugeridas:

## settings

```text
id
alert_threshold
check_interval_seconds
notifications_enabled
created_at
updated_at
```

## monitor_state

```text
id
last_balance
last_total_credits
last_total_usage
last_check_at
last_success_at
openrouter_status
evolution_status
alert_triggered
last_alert_at
last_alert_balance
updated_at
```

## events

```text
id
timestamp
event_type
balance
message
metadata_json
```

Não armazenar secrets no campo `metadata_json`.

---

# 15. Tipos de eventos

Usar enum/constantes em vez de strings espalhadas.

Tipos iniciais:

```text
BALANCE_CHECK
BALANCE_RECOVERED
ALERT_SENT
ALERT_REARMED
OPENROUTER_ERROR
WHATSAPP_TEST_SENT
WHATSAPP_ERROR
SETTINGS_CHANGED
MONITOR_STARTED
```

Evitar gravar uma quantidade ilimitada de verificações.

Definir política de retenção.

Sugestão:

```text
30 dias
```

ou limite máximo de registros.

A limpeza pode ocorrer diariamente.

---

# 16. Dinheiro / precisão

Não usar `float` para decisões monetárias.

Usar:

```text
Decimal
```

ou armazenamento inteiro em micros/cents quando aplicável.

A comparação:

```text
balance <= threshold
```

não pode sofrer erro binário de ponto flutuante.

SQLite pode armazenar os valores de forma compatível com a estratégia escolhida.

---

# 17. Healthchecks

Criar:

```text
GET /healthz
```

para indicar que o processo está vivo.

Resposta típica:

```json
{
  "status": "healthy"
}
```

Criar:

```text
GET /readyz
```

para verificar readiness local.

Pode validar:

- acesso ao SQLite;
- schema/migrations;
- scheduler inicializado;
- configuração mínima presente.

Não fazer `/healthz` depender da disponibilidade instantânea da:

- OpenRouter;
- Evolution API;
- WhatsApp.

Uma falha externa não significa que o processo local está morto.

A UI deve mostrar separadamente a saúde das integrações.

---

# 18. Observabilidade

Logs estruturados e legíveis.

Registrar:

- startup;
- shutdown;
- início/fim de verificações;
- erro da OpenRouter;
- mudança de configuração;
- alerta disparado;
- falha na Evolution;
- rearme.

Nunca registrar:

- Authorization header;
- OPENROUTER_MANAGEMENT_KEY;
- EVOLUTION_API_KEY;
- senha;
- cookies;
- conteúdo sensível.

Não imprimir payloads inteiros de erro caso possam conter secrets.

---

# 19. Timeouts e chamadas externas

Toda chamada HTTP externa deve possuir timeout explícito.

Exemplo inicial:

```text
connect: 5s
read: 10s
total razoável
```

Usar um cliente HTTP reutilizável.

Não permitir request infinito.

Retry deve ser:

- limitado;
- conservador;
- somente para erros apropriados;
- com backoff.

Não repetir automaticamente erro de autenticação 401/403.

---

# 20. Scheduler e múltiplos workers

Evitar iniciar múltiplas cópias do scheduler quando o servidor possuir mais de um worker.

Para este projeto simples, preferir:

```text
1 processo / 1 worker
```

se o scheduler estiver embutido no processo web.

Documentar explicitamente essa decisão.

Não escalar horizontalmente o container sem antes separar ou coordenar o scheduler.

---

# 21. Docker

Criar:

```text
Dockerfile
docker-compose.yml
.env.example
.dockerignore
```

Container deve:

- rodar como usuário não-root;
- possuir filesystem previsível;
- persistir apenas `/app/data`;
- usar `restart: unless-stopped`;
- ter healthcheck;
- não incluir secrets na imagem.

Exemplo conceitual:

```yaml
services:
  openrouter-credit-monitor:
    build: .
    restart: unless-stopped

    env_file:
      - .env

    volumes:
      - ./data:/app/data

    expose:
      - "8080"

    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8080/healthz"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
```

Preferir `expose` em vez de publicar porta host se a Central/reverse proxy estiver na mesma rede Docker.

Se publicação temporária for necessária para desenvolvimento local, deixá-la claramente separada da configuração de produção.

---

# 22. Configuração

Criar `.env.example`.

Exemplo:

```env
# Application
APP_ENV=production
APP_HOST=0.0.0.0
APP_PORT=8080
ROOT_PATH=/apps/openrouter-monitor

# OpenRouter
OPENROUTER_MANAGEMENT_KEY=

# Evolution API
EVOLUTION_API_URL=http://evolution-api:8080
EVOLUTION_API_KEY=
EVOLUTION_INSTANCE=openrouter-monitor
WHATSAPP_DESTINATION=

# Admin
ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH=

# Database
DATABASE_URL=sqlite:////app/data/monitor.db
```

O limite de alerta NÃO deve estar no `.env`.

Ele deve ser configurável pela UI e persistido no SQLite.

Valor inicial/default:

```text
10.00 USD
```

---

# 23. Estrutura sugerida

```text
openrouter-credit-monitor/
|
+-- app/
|   +-- main.py
|   |
|   +-- api/
|   |   +-- dashboard.py
|   |   +-- settings.py
|   |   +-- actions.py
|   |
|   +-- services/
|   |   +-- openrouter.py
|   |   +-- evolution.py
|   |   +-- monitor.py
|   |   +-- alerts.py
|   |
|   +-- scheduler/
|   |   +-- jobs.py
|   |
|   +-- db/
|   |   +-- database.py
|   |   +-- models.py
|   |   +-- migrations.py
|   |
|   +-- web/
|       +-- templates/
|       +-- static/
|
+-- tests/
|
+-- data/
|
+-- Dockerfile
+-- docker-compose.yml
+-- .env.example
+-- .gitignore
+-- .dockerignore
+-- pyproject.toml
+-- README.md
```

A estrutura pode ser ajustada se houver uma alternativa mais simples, mas manter clara separação entre:

```text
OpenRouter integration
Evolution integration
monitoring logic
alert logic
database
web/UI
scheduler
```

---

# 24. Endpoints internos sugeridos

Além das páginas HTML, disponibilizar endpoints administrativos coerentes.

Exemplo:

```text
GET  /healthz
GET  /readyz

GET  /
POST /settings
POST /actions/check-now
POST /actions/test-whatsapp
```

Não é necessário criar uma API pública completa.

Evitar endpoints sem uso.

---

# 25. Concorrência e idempotência

O alerta deve ser seguro contra duplicidade.

Cenário a evitar:

```text
check A encontra US$ 9.90
check B encontra US$ 9.90

A envia WhatsApp
B envia WhatsApp
```

A decisão e atualização do estado precisam ser coordenadas.

Para o modelo single-worker, usar:

- lock do monitor;
- transação SQLite;
- atualização de estado consistente.

O objetivo é garantir no máximo um alerta por ciclo de cruzamento do limite.

---

# 26. Caso de reinício

O estado de alerta NÃO pode ficar apenas em memória.

Exemplo:

```text
saldo = US$ 8
alerta já enviado
container reinicia
```

Depois do restart:

```text
saldo = US$ 8
```

não deve enviar outro alerta simplesmente porque o processo perdeu estado.

`alert_triggered` deve estar persistido no SQLite.

---

# 27. Inicialização

No primeiro startup:

1. validar configuração;
2. inicializar/migrar SQLite;
3. garantir defaults;
4. carregar estado;
5. iniciar scheduler;
6. executar uma verificação inicial de forma segura;
7. não enviar mensagem de teste automaticamente.

Default inicial:

```text
alert_threshold = 10.00
notifications_enabled = true
check_interval_seconds = 300
```

---

# 28. Alteração do intervalo

A primeira versão pode mostrar ou não o intervalo na Web UI.

Se implementado na UI:

- mínimo: 60 segundos;
- default: 300 segundos;
- validar entrada;
- reprogramar scheduler sem precisar reiniciar container.

Se isso aumentar desnecessariamente a complexidade, manter o intervalo fixo em 300 segundos na v1.

A prioridade da interface é permitir alterar o **limite monetário**.

---

# 29. Notificações habilitadas/desabilitadas

Adicionar:

```text
notifications_enabled
```

Quando `false`:

- continuar consultando saldo;
- continuar atualizando UI;
- continuar registrando estado;
- não enviar WhatsApp.

Ao reativar:

- avaliar o estado atual de forma previsível;
- não disparar múltiplas mensagens.

---

# 30. Testes obrigatórios

Criar testes automatizados pelo menos para a lógica crítica.

## OpenRouter

Testar:

- resposta válida;
- 401;
- 429;
- 500;
- timeout;
- JSON inválido;
- campos ausentes.

## Cálculo

Testar:

```text
total_credits - total_usage
```

com `Decimal`.

## Alert engine

Testar:

```text
saldo 15 / limite 10 -> sem alerta
saldo 10 / limite 10 -> alerta
saldo 9 / limite 10 -> alerta
```

Após alerta:

```text
saldo 8 -> sem novo alerta
saldo 7 -> sem novo alerta
```

Após recarga:

```text
saldo 30 -> rearmar
saldo 9 -> novo alerta
```

## Persistência

Testar que reiniciar/recriar o objeto de serviço não perde:

```text
alert_triggered
```

## Alteração de threshold

Testar alteração:

```text
10 -> 20
```

e:

```text
20 -> 5
```

com saldo atual em diferentes faixas.

## Evolution

Mockar HTTP.

Testar:

- sucesso;
- timeout;
- HTTP error;
- falha de autenticação;
- nenhum `alert_triggered=true` quando envio falha.

## Concorrência

Testar que duas chamadas simultâneas não enviam dois alertas.

---

# 31. Critérios de aceite

A implementação só deve ser considerada pronta quando os seguintes cenários forem demonstrados.

## Cenário A — normal

```text
threshold = 10
balance = 25
```

Resultado:

```text
nenhuma mensagem
UI mostra US$ 25
status NORMAL
```

## Cenário B — cruzamento

```text
threshold = 10
balance anterior = 11
balance atual = 9.90
```

Resultado:

```text
uma mensagem WhatsApp
alert_triggered=true
```

## Cenário C — permanece baixo

```text
balance = 8
```

Resultado:

```text
nenhuma nova mensagem
```

## Cenário D — recarga

```text
balance = 30
```

Resultado:

```text
monitor rearmado
alert_triggered=false
```

## Cenário E — segunda queda

```text
balance = 9
```

Resultado:

```text
uma nova mensagem
```

## Cenário F — OpenRouter indisponível

Resultado:

```text
não inventar saldo zero
não disparar alerta
UI mostra erro da integração
mantém último saldo conhecido
```

## Cenário G — Evolution indisponível

Resultado:

```text
registrar falha
não marcar alerta como enviado
retry controlado
sem loop de spam
```

## Cenário H — reinício

Com:

```text
alert_triggered=true
balance < threshold
```

reiniciar o container.

Resultado:

```text
não enviar alerta duplicado
```

## Cenário I — Web UI

Alterar:

```text
threshold: 10 -> 15
```

Resultado:

```text
valor persistido
sobrevive restart
scheduler usa novo valor
```

## Cenário J — integração com Central

O app deve funcionar corretamente em:

```text
https://proartelab.com/apps/openrouter-monitor
```

incluindo:

- CSS;
- formulários;
- redirects;
- ações;
- assets.

Sem subdomínio próprio.

---

# 32. README

O README deve explicar:

1. objetivo do projeto;
2. arquitetura;
3. requisitos;
4. como gerar/configurar credenciais;
5. variáveis de ambiente;
6. como executar localmente;
7. como executar com Docker;
8. como conectar à Evolution API;
9. como configurar `ROOT_PATH`;
10. como integrar com a Central de Apps;
11. como executar testes;
12. como fazer backup do SQLite;
13. como atualizar o container;
14. troubleshooting.

Não incluir secrets reais.

---

# 33. Instruções para implementação pelo Claude

Implemente o projeto completo seguindo esta especificação.

Antes de escrever código:

1. revise toda a especificação;
2. identifique qualquer contradição;
3. escolha a solução mais simples e conservadora;
4. não aumente o escopo sem necessidade;
5. preserve a arquitetura single-container para o monitor;
6. mantenha a Evolution API como dependência externa/separada;
7. não crie subdomínios;
8. garanta suporte ao path prefix `/apps/openrouter-monitor`.

Ao integrar APIs externas:

- use a documentação oficial atual;
- não invente endpoints;
- confirme o contrato atual da OpenRouter;
- confirme a versão da Evolution API antes de fixar endpoints específicos;
- mantenha os clients externos isolados em adapters.

Implemente por etapas pequenas e verificáveis.

Use TDD para a lógica crítica de:

- saldo;
- threshold;
- disparo;
- anti-spam;
- rearme;
- persistência;
- falha de envio.

Não marque a tarefa como concluída apenas porque o servidor inicia.

Execute os testes e valide os critérios de aceite.

Ao final, entregue:

```text
IMPLEMENTATION_STATUS
ARCHITECTURE
FILES_CREATED
TESTS
TEST_RESULTS
DOCKER_STATUS
OPENROUTER_INTEGRATION
EVOLUTION_INTEGRATION
WEB_UI
CENTRAL_PATH_PREFIX
SECURITY_NOTES
KNOWN_LIMITATIONS
MANUAL_CONFIGURATION_REQUIRED
FINAL_STATUS
```

Em `MANUAL_CONFIGURATION_REQUIRED`, liste apenas dados realmente necessários do operador, como:

```text
OPENROUTER_MANAGEMENT_KEY
EVOLUTION_API_URL
EVOLUTION_API_KEY
EVOLUTION_INSTANCE
WHATSAPP_DESTINATION
ADMIN credentials
```

Nunca invente valores.

---

# 34. Restrições finais

Obrigatório:

```text
NO AI REQUIRED
NO LLM REQUIRED
NO SUBDOMAIN
NO SCRAPING
NO SECRET IN DATABASE
NO SECRET IN UI
NO FLOAT FOR MONEY
NO ALERT LOOP
NO FALSE ZERO BALANCE
NO DUPLICATE ALERT AFTER RESTART
NO PUBLIC DIRECT PORT REQUIRED IN PRODUCTION
```

Resultado esperado:

```text
OpenRouter
   |
   v
Credit Monitor
   |
   +--> Web UI em proartelab.com/apps/openrouter-monitor
   |
   +--> SQLite
   |
   +--> Alert Engine
            |
            v
       Evolution API
            |
            v
         WhatsApp
```

O app deve fazer somente isso e fazer de forma previsível, segura e fácil de manter.
