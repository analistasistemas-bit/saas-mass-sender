# 1. VISÃO GERAL DO SISTEMA

- O sistema atual é um console web para operação de campanhas de envio em massa via WhatsApp.
- O produto permite criar campanhas, importar base de contatos (CSV), validar telefones BR, enviar amostra obrigatória (test-run), iniciar envio real, pausar/retomar/cancelar e exportar falhas.
- O backend principal é FastAPI (Python) e o envio padrão usa um bridge local em Node.js (`wa-bridge`) com `whatsapp-web.js`.
- Existe compatibilidade legada com Evolution API, mas o fluxo padrão em produção local/VPS está em `WHATSAPP_PROVIDER=bridge`.
- O sistema possui login único por senha administrativa (`APP_ADMIN_PASSWORD`) com cookie simples.

- Principais funcionalidades implementadas hoje:
- Gestão de campanhas com estados: `draft`, `ready`, `running`, `paused`, `cancelled`, `completed`.
- Upload CSV com parser robusto para formato padrão e legado.
- Normalização para E.164 brasileiro (`+55...`) e marcação de contatos inválidos.
- Cadastro manual de contatos além do CSV.
- Simulação (`dry-run`) com preview e estimativa.
- Amostra (`test-run`) antes do envio real.
- Worker assíncrono persistente (polling em banco) com retry para erro temporário.
- Controles operacionais por campanha: delays, pausa entre lotes, janela horária, limite diário.
- Auto-pausa por limite diário, falhas consecutivas e indisponibilidade de serviços.
- Auto-recuperação do motor de envio e do bridge WhatsApp.
- Visão operacional no frontend com status de serviços, resultados agregados e incidentes.

- Fluxo principal do usuário:
- Login em `/login`.
- Home (`/`) para conferir estado do WhatsApp e criar/abrir campanha.
- Tela da campanha (`/campaigns/{id}`): editar mensagem, ajustar configuração operacional, importar contatos, simular, testar, iniciar, acompanhar e exportar falhas.
- A interface faz polling para `/campaigns/{id}/stats`, `/campaigns/{id}/overview`, `/bridge/session` e `/campaigns/{id}/contacts`.

- Tecnologias utilizadas:
- Backend: Python 3 + FastAPI + SQLAlchemy + SQLite + Jinja2.
- Frontend: server-rendered templates Jinja2 + JavaScript vanilla + Tailwind CDN + CSS custom.
- Bridge WhatsApp: Node.js + Express + `whatsapp-web.js` + Chromium (Puppeteer runtime).
- Testes: Pytest (backend), Playwright (E2E da UI), `node:test` no bridge.
- Deploy: Docker Compose em VPS + GitHub Actions (deploy por SSH).

---

# 2. ARQUITETURA ATUAL

## Backend

- Linguagem:
- Python.

- Framework:
- FastAPI com rotas HTTP síncronas e assíncronas.

- Organização de pastas:
- `main.py`: bootstrap da app, autenticação, rotas HTTP e supervisão de serviços.
- `services/`: regra de negócio e integração (`campaign_service`, `send_engine`, `whatsapp`).
- `models.py`: entidades SQLAlchemy (`Campaign`, `Contact`, `SendLog`).
- `database.py`: engine SQLite, sessão e PRAGMAs.
- `utils/`: parser CSV, telefone, composição de mensagem, limites e janela.

- Principais módulos:
- `services/campaign_service.py`: ciclo de campanha, upload, contatos manuais, payloads de stats/overview, logs.
- `services/send_engine.py`: loop assíncrono do worker, batching adaptativo, retries, recovery e health interno.
- `services/whatsapp.py`: cliente para provider `bridge` ou `evolution`.

## Frontend

- Tipo (SSR, SPA, HTML puro):
- SSR com Jinja2 no primeiro render + comportamento de SPA parcial por JavaScript (polling e ações via `fetch`).

- Tecnologias usadas:
- Templates Jinja2 (`templates/*.html`), JavaScript vanilla (`static/*.js`), Tailwind via CDN e CSS local (`static/styles.css`).

- Estrutura de templates:
- `templates/login.html`: login por senha.
- `templates/index.html`: dashboard home (conexão WhatsApp + criação/lista de campanhas).
- `templates/campaign.html`: console operacional completo da campanha.

## Integrações

- WhatsApp bridge:
- `wa-bridge` em Node.js expõe `/health`, `/session`, `/session/qr`, `/session/restart`, `/session/reset`, `/messages/send-text` e `/numbers/resolve`.
- O backend FastAPI consome esses endpoints via `httpx`.

- APIs externas:
- Evolution API (legado/opcional) por `EVOLUTION_BASE_URL` + instância + API key.

- Dependências externas:
- `whatsapp-web.js` (não oficial) e Chromium headless.
- Google Fonts/Tailwind CDN no frontend.
- GitHub Actions para CI/CD.

---

# 3. ESTRUTURA DE PASTAS (CRÍTICO)

- Observação de escopo da árvore:
- O repositório contém artefatos muito grandes e gerados (`.git`, `node_modules`, `.venv`, cache Chrome em `wa-bridge/.wwebjs_auth`, vendor gigante em `.vendor/evolution-api`, worktree em `.worktrees/local-testing`).
- A árvore abaixo cobre a estrutura operacional do projeto principal, incluindo diretórios de documentação e testes; os artefatos gigantes são listados como existentes, mas não expandidos integralmente para manter legibilidade.

```text
.
├── main.py
├── database.py
├── models.py
├── schemas.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── docker-compose.evolution.yml
├── .env
├── .env.example
├── app.db
├── app.db-wal
├── app.db-shm
├── README.md
├── services/
│   ├── campaign_service.py
│   ├── send_engine.py
│   └── whatsapp.py
├── utils/
│   ├── config.py
│   ├── csv_parser.py
│   ├── phone.py
│   ├── message_compose.py
│   ├── daily_limit.py
│   ├── schedule_guard.py
│   └── speed_profiles.py
├── templates/
│   ├── login.html
│   ├── index.html
│   └── campaign.html
├── static/
│   ├── common.js
│   ├── index.js
│   ├── app.js
│   └── styles.css
├── tests/
│   ├── test_bridge_routes.py
│   ├── test_campaign_actions_ui_payloads.py
│   ├── test_campaign_state.py
│   ├── test_csv_parser.py
│   ├── test_env_loading.py
│   ├── test_operational_controls.py
│   ├── test_phone.py
│   ├── test_send_engine.py
│   ├── test_template.py
│   ├── test_test_run_diagnostics.py
│   ├── test_test_run_route.py
│   ├── test_whatsapp_client.py
│   ├── test_whatsapp_errors.py
│   ├── fixtures/contatos_e2e.csv
│   └── e2e/
│       ├── operational.spec.js
│       └── operational-feedback.spec.js
├── wa-bridge/
│   ├── server.js
│   ├── fetch-qr.js
│   ├── Dockerfile
│   ├── package.json
│   ├── package-lock.json
│   ├── lib/
│   │   ├── process-guard.js
│   │   └── recipient-resolver.js
│   ├── tests/
│   │   ├── process-guard.test.js
│   │   └── recipient-resolver.test.js
│   ├── .wwebjs_auth/               (sessão WhatsApp persistida)
│   └── .wwebjs_cache/              (cache do WhatsApp Web)
├── docs/
│   ├── OPERATIONS.md
│   ├── USER_GUIDE.md
│   ├── OPERATIONAL_CONTROLS.md
│   ├── VPS-OPERATIONS.md
│   ├── LOCAL_ENVIRONMENT.md
│   ├── TESTING_RESOLUTION.md
│   ├── plans/*
│   └── superpowers/*
├── .github/workflows/deploy.yml
├── package.json                    (Playwright e2e)
├── package-lock.json
├── playwright.config.js
├── pytest.ini
├── instructions.md
├── bugs/
├── .worktrees/local-testing/       (worktree duplicando a app)
├── .vendor/evolution-api/          (vendor externo grande)
└── test-results/
```

- Responsabilidades por pasta:
- `services/`: domínio de campanha, motor de envio e integração de provider.
- `utils/`: validações e regras reutilizáveis (telefone, CSV, janela, limites, perfil de velocidade).
- `templates/` e `static/`: interface operacional.
- `wa-bridge/`: sessão WhatsApp e envio via `whatsapp-web.js`.
- `tests/`: cobertura backend, bridge e E2E frontend.
- `docs/`: operação, uso e planos de evolução.

---

# 4. BANCO DE DADOS

## Tipo

- SQLite (arquivo local configurado por `DB_PATH`; padrão `app.db`).
- PRAGMAs aplicados em conexão (`database.py`):
- `journal_mode=WAL`
- `synchronous=NORMAL`
- `foreign_keys=ON`

## Estrutura atual

- Tabela `campaigns`:
- `id INTEGER PK`
- `name VARCHAR(140) NOT NULL`
- `message_template TEXT NOT NULL`
- `status VARCHAR(20) NOT NULL`
- `is_test_required INTEGER NOT NULL`
- `test_completed_at DATETIME NULL`
- `total_contacts INTEGER NOT NULL`
- `valid_contacts INTEGER NOT NULL`
- `invalid_contacts INTEGER NOT NULL`
- `sent_count INTEGER NOT NULL`
- `failed_count INTEGER NOT NULL`
- `pending_count INTEGER NOT NULL`
- `started_at DATETIME NULL`
- `finished_at DATETIME NULL`
- `created_at DATETIME NOT NULL`
- `updated_at DATETIME NOT NULL`
- `send_delay_min_seconds INTEGER NOT NULL DEFAULT 15`
- `send_delay_max_seconds INTEGER NOT NULL DEFAULT 45`
- `daily_limit INTEGER NOT NULL DEFAULT 0`
- `sent_today INTEGER NOT NULL DEFAULT 0`
- `last_send_date DATETIME NULL`
- `pause_reason VARCHAR(80) NULL`
- `speed_profile VARCHAR(20) NOT NULL DEFAULT 'conservative'`
- `batch_pause_min_seconds INTEGER NOT NULL DEFAULT 25`
- `batch_pause_max_seconds INTEGER NOT NULL DEFAULT 40`
- `batch_size_initial INTEGER NOT NULL DEFAULT 10`
- `batch_size_max INTEGER NOT NULL DEFAULT 25`
- `batch_growth_step INTEGER NOT NULL DEFAULT 2`
- `batch_growth_streak_required INTEGER NOT NULL DEFAULT 3`
- `batch_shrink_step INTEGER NOT NULL DEFAULT 2`
- `batch_shrink_error_streak_required INTEGER NOT NULL DEFAULT 2`
- `batch_size_floor INTEGER NOT NULL DEFAULT 5`
- `send_window_start_hour INTEGER NOT NULL DEFAULT 8`
- `send_window_end_hour INTEGER NOT NULL DEFAULT 20`

- Tabela `contacts`:
- `id INTEGER PK`
- `campaign_id INTEGER NOT NULL FK -> campaigns.id ON DELETE CASCADE`
- `name VARCHAR(120) NOT NULL`
- `phone_raw VARCHAR(40) NOT NULL`
- `phone_e164 VARCHAR(20) NULL`
- `email VARCHAR(255) NOT NULL`
- `status VARCHAR(20) NOT NULL`
- `error_message TEXT NULL`
- `attempt_count INTEGER NOT NULL`
- `last_attempt_at DATETIME NULL`
- `sent_at DATETIME NULL`
- `created_at DATETIME NOT NULL`
- `updated_at DATETIME NOT NULL`
- `source VARCHAR(20) NOT NULL DEFAULT 'csv'`
- Índices e constraints:
- `UNIQUE(campaign_id, phone_e164)` (`uq_contacts_campaign_phone`)
- `INDEX ix_contacts_campaign_status(campaign_id, status)`

- Tabela `send_logs`:
- `id INTEGER PK`
- `campaign_id INTEGER NOT NULL FK -> campaigns.id ON DELETE CASCADE`
- `contact_id INTEGER NULL FK -> contacts.id ON DELETE SET NULL`
- `event_type VARCHAR(40) NOT NULL`
- `payload_excerpt TEXT NULL`
- `http_status INTEGER NULL`
- `error_class VARCHAR(20) NULL`
- `created_at DATETIME NOT NULL`
- Índices: não há índice explícito nesta tabela.

- Relacionamentos:
- `campaigns 1:N contacts`
- `campaigns 1:N send_logs`
- `contacts 1:N send_logs` (com `contact_id` opcional)

## Observações

- Limitações atuais:
- Sem migração versionada (Alembic); ajuste de schema é feito em runtime por `ensure_campaign_operational_columns`.
- Não há isolamento por tenant/usuário no banco.
- Sem índices para consultas frequentes em `send_logs` por `campaign_id/event_type/created_at`.

- Problemas conhecidos/inconsistências verificadas:
- Inconsistência de defaults entre código e migração runtime:
- `models.py` define `batch_size_initial=5`, `batch_size_max=15`, `batch_pause_min_seconds=25`, `batch_pause_max_seconds=40`.
- `ensure_campaign_operational_columns` (main.py) cria colunas ausentes com defaults `batch_size_initial=10`, `batch_size_max=25`, `batch_pause_min_seconds=5`, `batch_pause_max_seconds=10` e faz backfill para esses valores quando `NULL`.
- Resultado: dependendo da origem do banco/linha, campanhas podem nascer com perfis diferentes.

---

# 5. FLUXO DE CAMPANHAS

- Como uma campanha é criada:
- `POST /campaigns` chama `create_campaign`.
- Cria em `draft` com template inicial `Oi, {{nome}}`.
- Página da campanha em `GET /campaigns/{id}` com métricas, contatos paginados e status de serviços.

- Como contatos são carregados:
- CSV: `POST /campaigns/{id}/contacts/upload`.
- Parser `parse_csv_bytes` valida UTF-8, headers padrão/legado e normaliza telefone BR.
- Antes de inserir, remove contatos anteriores de `source='csv'` da mesma campanha.
- Contatos manuais (`source='manual'`) são preservados.
- Status inicial por linha: `pending` se válido, `invalid` se inválido.
- Duplicidade na mesma campanha é bloqueada por `UNIQUE(campaign_id, phone_e164)`.
- Contato manual: `POST /campaigns/{id}/contacts/manual` valida nome/telefone, cria `pending`.

- Como envio acontece:
- Pré-condição: `start_campaign` exige test-run concluído (`test_completed_at`) para campanha inédita.
- `POST /campaigns/{id}/start` muda para `running` e worker passa a processar.
- Worker `SendEngine.run_forever` busca campanhas `running` (e algumas `paused` em recuperação).
- Por campanha, pega lote de contatos `pending`, marca `processing`, envia um a um via `WhatsAppClient.send_text`.
- Em sucesso: contato vira `sent`, incrementa contadores e `sent_today`.

- Como logs são gerados:
- `send_logs` recebe eventos por `log_event`.
- Eventos comuns: `send_attempt`, `send_success`, `retry_scheduled`, `send_failure`, `campaign_state_change`, `send_window_wait`, eventos de auto-pausa/auto-resume/recovery.
- Frontend usa `/campaigns/{id}/overview` para consolidar resultados/incidentes a partir desses logs.

- Como falhas são tratadas:
- Erro temporário (`error_class='temporary'`): retry até `attempt_count < 3`, contato volta para `pending` com `retry_scheduled`.
- Erro permanente ou esgotamento: contato `failed`, evento `send_failure`.
- Erro de sessão (`error_class='session'`): contato volta `pending`, campanha entra em recuperação de bridge.
- 5 falhas consecutivas no runtime: campanha auto-pausada com `pause_reason='consecutive_failures'`.
- Limite diário atingido: campanha auto-pausada com `pause_reason='daily_limit_reached'`.

---

# 6. SISTEMA DE ENVIO

- Como funciona o `send_engine`:
- Instância global (`engine_worker`) criada em `main.py`.
- Startup inicia task `run_forever`; supervisor separado monitora heartbeat e reinicia worker quando necessário.
- Processamento por campanha com lock em memória (`self._locks`) para evitar concorrência local duplicada da mesma campanha.

- Se é síncrono ou assíncrono:
- Assíncrono (asyncio) com loop contínuo e tarefas paralelas por campanha (`asyncio.create_task` + `gather`).
- Persistência de estado no banco; não usa fila externa (Redis/Celery).

- Como controla delay:
- Delay entre contatos: `random.uniform(send_delay_min_seconds, send_delay_max_seconds)`.
- Pausa entre lotes: `random.uniform(batch_pause_min_seconds, batch_pause_max_seconds)`.
- Fora da janela horária: espera até próxima janela com `seconds_until_next_window`.

- Como controla erro:
- Classificação de erro no `WhatsAppClient` (`temporary`, `permanent`, `session`).
- Retry para temporário (até 3 tentativas por contato).
- Pausa automática por 5 falhas consecutivas.
- Recovery automático de bridge e do próprio worker.

- Como evita duplicidade (se evita):
- Evita duplicidade de telefone apenas dentro da mesma campanha (`UNIQUE(campaign_id, phone_e164)`).
- Não existe mecanismo de deduplicação global entre campanhas.
- Não existe idempotency key por mensagem enviada; duplicidade entre campanhas/reinícios é possível por desenho funcional.

---

# 7. WHATSAPP BRIDGE

- Tecnologia usada (wwebjs, puppeteer, etc):
- `whatsapp-web.js` com Chromium headless.
- Servidor Express (`wa-bridge/server.js`).

- Como a sessão é armazenada:
- `LocalAuth` do `whatsapp-web.js` com `clientId` e `dataPath`.
- Padrão: `WA_SESSION_NAME=mass-sender` e `WA_DATA_PATH=.wwebjs_auth`.

- Onde fica a sessão:
- Localmente no projeto: `wa-bridge/.wwebjs_auth/session-mass-sender`.
- Em Docker Compose produção: volume `wa_sessions` montado em `/app/.wwebjs_auth`.

- Como QR é gerado:
- Evento `client.on('qr')` gera Data URL PNG (`qrcode` lib), salva em memória (`state.qrDataUrl`).
- Endpoint `GET /session/qr` retorna base64.
- Script `fetch-qr.js` busca `/session/qr` e grava PNG em `/tmp/mass-sender-wa-qr.png` (ou `WA_BRIDGE_QR_PATH`).

- Como reconexão funciona:
- Bridge tenta `initialize()` e, em erro de browser preso (`The browser is already running for...`), roda cleanup de lock/processo (`process-guard`) e tenta novamente.
- Em falha de sessão durante envio, backend pausa campanha (`bridge_recovering`) e tenta `POST /session/restart` automaticamente.
- Há `POST /session/reset` para reset completo (inclui remoção da pasta da sessão).
- `send_engine.monitor_bridge_service()` tenta restart periódico e retoma campanhas automaticamente quando sessão volta saudável.

---

# 8. CONFIGURAÇÕES E VARIÁVEIS DE AMBIENTE

- Variáveis usadas no runtime atual (código Python + wa-bridge):
- `APP_ADMIN_PASSWORD`
- Função: senha de login do painel e valor comparado ao cookie de sessão.
- Exemplo: `APP_ADMIN_PASSWORD=admin123`

- `DB_PATH`
- Função: caminho do SQLite.
- Exemplo: `DB_PATH=app.db`

- `WHATSAPP_PROVIDER`
- Função: seleciona provider (`bridge` ou `evolution`).
- Exemplo: `WHATSAPP_PROVIDER=bridge`

- `WA_BRIDGE_BASE_URL`
- Função: URL base do bridge para o backend Python.
- Exemplo: `WA_BRIDGE_BASE_URL=http://127.0.0.1:3010`

- `WA_BRIDGE_API_KEY`
- Função: autenticação entre app e bridge via header `x-api-key`.
- Exemplo: `WA_BRIDGE_API_KEY=`

- `EVOLUTION_BASE_URL`
- Função: URL da Evolution API (modo legado).
- Exemplo: `EVOLUTION_BASE_URL=http://localhost:8080`

- `EVOLUTION_INSTANCE`
- Função: nome da instância Evolution.
- Exemplo: `EVOLUTION_INSTANCE=minha-instancia`

- `EVOLUTION_API_KEY`
- Função: chave de API Evolution.
- Exemplo: `EVOLUTION_API_KEY=troque-esta-chave`

- `WA_BRIDGE_PORT`
- Função: porta do bridge.
- Exemplo: `WA_BRIDGE_PORT=3010`

- `WA_BRIDGE_HOST`
- Função: host bind do bridge.
- Exemplo: `WA_BRIDGE_HOST=127.0.0.1` (local) / `0.0.0.0` (docker)

- `WA_SESSION_NAME`
- Função: nome lógico da sessão LocalAuth.
- Exemplo: `WA_SESSION_NAME=mass-sender`

- `WA_DATA_PATH`
- Função: diretório base de sessão/cache do WhatsApp.
- Exemplo: `WA_DATA_PATH=.wwebjs_auth`

- `WA_HEADLESS`
- Função: modo headless do Chromium (`false` desativa).
- Exemplo: `WA_HEADLESS=true`

- `WA_EXECUTABLE_PATH`
- Função: caminho do Chromium no bridge.
- Exemplo: `WA_EXECUTABLE_PATH=/usr/bin/chromium`

- `WA_RETRY_MS`
- Função: intervalo de retentativa de inicialização do bridge.
- Exemplo: `WA_RETRY_MS=5000`

- `WA_BRIDGE_QR_PATH`
- Função: caminho de saída do PNG gerado por `fetch-qr.js`.
- Exemplo: `WA_BRIDGE_QR_PATH=/tmp/mass-sender-wa-qr.png`

- Observação:
- O loader de `.env` (`utils/config.py`) usa `os.environ.setdefault`; variáveis já exportadas no shell têm prioridade sobre `.env`.

---

# 9. DOCKER E DEPLOY

## Docker

- Dockerfile(s):
- `Dockerfile` (app FastAPI): instala requirements e sobe `uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1`.
- `wa-bridge/Dockerfile`: `node:20-slim`, instala Chromium + libs, define `WA_EXECUTABLE_PATH`, roda `node server.js`.

- docker-compose:
- `docker-compose.yml` (fluxo padrão):
- Serviço `wa-bridge` com volume persistente `wa_sessions`.
- Serviço `app` com volume `app_data` para SQLite em `/data/app.db`.
- `app` publicado somente em `127.0.0.1:8000`.
- Comunicação interna app -> bridge por `http://wa-bridge:3010`.

- `docker-compose.evolution.yml` (legado):
- `evolution-api` + `postgres` + `redis`.

- serviços existentes:
- Padrão atual: `app` e `wa-bridge`.
- Legado opcional: `evolution-api`, `evolution-postgres`, `evolution-redis`.

## Infra

- VPS:
- Documentação operacional aponta Hostinger VPS com app em `/opt/mass-sender`.

- Cloudflare:
- Documentado como camada externa TLS/roteamento.
- Configuração citada: SSL Flexible (segundo `docs/VPS-OPERATIONS.md`).

- OpenClaw:
- Não há configuração OpenClaw no código do repositório.
- Há referência textual em comentário de `docker-compose.yml` ("OpenClaw/Nginx faz o proxy público").
- Status: não identificado tecnicamente no projeto; investigar fora do repo (infra da VPS).

- Nginx (se houver):
- Não existe arquivo de Nginx dentro deste repositório.
- `docs/VPS-OPERATIONS.md` descreve Nginx no host VPS com proxy para `127.0.0.1:8000`.

## Fluxo de deploy

- Manual ou CI/CD:
- Ambos existem.

- GitHub Actions (se existir):
- Existe `.github/workflows/deploy.yml`.
- Trigger: `push` em `main`.
- Fluxo: SSH na VPS -> `git fetch` + `git reset --hard origin/main` -> `docker compose build app` -> `docker compose up -d` -> healthcheck em `http://127.0.0.1:8000/health` -> prune de imagens.

---

# 10. AUTENTICAÇÃO

- existe login?
- Sim.

- como funciona:
- `GET /login` renderiza formulário.
- `POST /login` compara `password` com `APP_ADMIN_PASSWORD`.
- Se válido, define cookie `mass_sender_admin` com o valor literal da senha.

- onde é validado:
- Dependência `require_auth` em `main.py` para quase todas as rotas, exceto `/login*` e `/health`.

- como sessão é mantida:
- Cookie HTTP-only simples (`SESSION_COOKIE='mass_sender_admin'`) com `samesite='lax'`.
- Não há expiração explícita, assinatura criptográfica, rotação, CSRF token ou store de sessão.

---

# 11. MULTIUSUÁRIO (OU AUSÊNCIA DELE)

- existe suporte a múltiplos usuários?
- Não.

- como está implementado:
- Um único segredo global (`APP_ADMIN_PASSWORD`).
- Interface mostra usuário fixo "Admin".
- Não há tabela de usuários, papéis, ACL, tenant_id ou segregação de dados por conta.

- limitações:
- Todos os operadores compartilham mesma credencial e mesmo escopo de dados.
- Auditoria por usuário não existe.
- Impossível separar campanhas por cliente/empresa sem refatoração estrutural.

---

# 12. LIMITAÇÕES ATUAIS (CRÍTICO)

- técnicos:
- Sem sistema formal de migração de banco (Alembic).
- Dependência de polling HTTP e worker em processo único.
- Sem fila distribuída (Redis/Celery/Rabbit).
- `send_logs` sem índices dedicados para consultas grandes.

- arquiteturais:
- Forte acoplamento app + bridge local.
- Estado de lock/concurrency do worker é em memória do processo.
- Sem multi-tenant e sem boundaries de domínio para SaaS.

- de performance:
- SQLite pode degradar sob alto volume concorrente e consultas grandes de logs.
- `refresh_campaign_counters` recalcula contagens com queries frequentes.
- Frontend faz polling de múltiplos endpoints a cada 10s (e 5s na home para bridge).

- de UX:
- Fluxo depende de múltiplas ações manuais para operação segura.
- Sem notificações push/WebSocket.
- Alguns estados são derivados por heurística de frontend quando `/overview` falha.

- de segurança:
- Sessão baseada em cookie contendo a própria senha admin.
- Sem hashing/gestão de usuários.
- Sem CSRF explícito em formulários.
- Dependência de stack não oficial (`whatsapp-web.js`) com risco operacional/regulatório.

---

# 13. GARGALOS IDENTIFICADOS

- onde pode quebrar:
- Queda do `wa-bridge` ou sessão instável do Chromium/WhatsApp Web.
- Reinício do processo da app durante campanha pode pausar/retomar fora da expectativa operacional imediata.

- onde não escala:
- Crescimento de `send_logs` sem índice dedicado.
- SQLite para alto throughput e múltiplas campanhas simultâneas de grande volume.
- Worker único com throughput limitado a uma instância de processo.

- pontos frágeis:
- Inconsistência de defaults operacionais (modelo vs bootstrap runtime).
- Dependência de health/recovery heurística para bridge.
- Deploy com `git reset --hard` no servidor pode descartar ajustes manuais locais.

---

# 14. LOGS E MONITORAMENTO

- como logs são feitos:
- Logs funcionais de campanha no banco (`send_logs`) por evento.
- Logs de processo via stdout/stderr do `uvicorn` e do `wa-bridge`.

- onde são armazenados:
- Eventos funcionais: tabela SQLite `send_logs`.
- Logs de runtime: containers Docker (`docker compose logs`) e, no host, logs padrão de serviço/proxy.

- se existe monitoramento:
- Há monitoramento interno básico no `SendEngine`:
- heartbeat do worker.
- status dos serviços (`worker`, `bridge`) com estado `operational/recovering/degraded/down`.
- alerta mais recente (`latest_alert`) exposto em `/campaigns/{id}/stats`.
- Não existe plataforma dedicada de observabilidade (Prometheus/Grafana/Sentry) no código atual.

---

# 15. PONTOS DE RISCO

- risco de perda de dados:
- Moderado: SQLite local com volume persistente reduz risco, mas backup/restore é manual.
- Alto se volumes Docker forem removidos sem backup (`app_data`, `wa_sessions`).

- risco de duplicidade:
- Existe risco entre campanhas diferentes (não há dedupe global).
- Em reprocessamentos intencionais (`restart all/failed`), o reenvio pode duplicar mensagens por desenho funcional.

- risco de travamento:
- Sessão Chromium/WhatsApp pode entrar em estado quebrado (`detached frame`), exigindo recovery.
- Worker pode ficar sem heartbeat; existe mecanismo de autorecovery, mas não elimina risco de degradação.

- risco de falha silenciosa:
- Parcialmente mitigado por `send_logs` e service health.
- Ainda há risco de incidentes não percebidos rapidamente sem monitoramento externo/alerta ativo.

---

# 16. O QUE NÃO ESTÁ IMPLEMENTADO MAS É NECESSÁRIO

- features ausentes importantes:
- Multiusuário real (usuários, RBAC, segregação por tenant/conta).
- Autenticação robusta (hash de senha, sessão assinada, rotação, CSRF).
- Auditoria por operador e trilha de mudança.
- Dashboard de observabilidade/alerting externo.

- arquitetura faltando:
- Banco transacional mais robusto para escala (PostgreSQL) no core da aplicação.
- Sistema de filas/background distribuído.
- Migrações versionadas de schema.
- Contratos de integração mais resilientes (idempotência, retries observáveis, DLQ).

- melhorias obrigatórias para evolução segura:
- Eliminar inconsistência de defaults operacionais entre modelo/bootstrap.
- Adicionar índices em `send_logs` por `campaign_id`, `event_type`, `created_at`.
- Definir estratégia de backup automático e restore testado.
- Formalizar estratégia de deploy sem reset destrutivo de estado local operacional.

---

# 17. RESUMO TÉCNICO FINAL

- nível atual do sistema (MVP, intermediário, avançado):
- MVP avançado operacional (bom nível de fluxo e controles para operação manual), mas ainda não arquitetura SaaS escalável.

- principais dívidas técnicas:
- autenticação/sessão frágil e sem multiusuário.
- ausência de migrações versionadas.
- acoplamento forte com `whatsapp-web.js` local.
- uso de SQLite para domínio que tende a crescer em concorrência e volume.
- inconsistência de defaults operacionais entre pontos do código.

- facilidade de evolução (alta/média/baixa):
- Média para evolução incremental local.
- Baixa para evolução segura em direção a SaaS multi-tenant de alta escala sem refatorações estruturais.

- Itens não identificados claramente no código e onde investigar:
- OpenClaw: somente referência textual; investigar na infraestrutura da VPS fora do repositório.
- Configuração real de Nginx/Cloudflare: descrita em documentação, mas arquivos efetivos não estão versionados aqui; validar diretamente no host (`/etc/nginx` e painel Cloudflare).
