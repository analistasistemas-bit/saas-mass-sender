# Plano Definitivo: Evolução para SaaS Multi-Tenant Empresarial

## Contexto

Sistema atual: single-user, SQLite, senha única, uma sessão WhatsApp global, 3 templates Jinja2.
Objetivo: SaaS multi-tenant com organizações isoladas, RBAC completo, sessões WhatsApp por org,
painel admin global e dashboard por organização. Monetizável, escalável, profissional.

Esta é uma **reescrita arquitetural**, não uma feature. O código de negócio central (send engine,
phone normalization, CSV parser, speed profiles) é reaproveitado. A casca toda (auth, modelos,
rotas, templates) é reconstruída.

---

## Stack Definitiva

| Camada | Tecnologia | Justificativa |
|---|---|---|
| Backend | FastAPI 0.115+ (manter) | Já dominado, async nativo |
| ORM | SQLAlchemy 2.0 (manter) | Apenas trocar engine |
| Banco | **PostgreSQL 16** | Multi-tenant exige ACID real, JSON fields, índices parciais |
| Migrations | **Alembic** | Controle de schema versionado |
| Auth | **JWT** (access 1h + refresh 30d via cookie) | Stateless, escalável |
| Hashing | **bcrypt** | Padrão de mercado |
| Config | **pydantic-settings** | Type-safe env vars |
| Frontend | Jinja2 + Tailwind CSS + Vanilla JS modular | Manter stack, modernizar layout |
| Bridge WA | Node.js (manter) + multi-session refactor | Um processo, N sessões Chromium |
| Container | Docker Compose + serviço PostgreSQL | Adição mínima |

**Dependências novas em requirements.txt:**
```
asyncpg==0.29.0          # Driver PostgreSQL async
psycopg2-binary==2.9.10  # Driver PostgreSQL sync (Alembic)
alembic==1.14.0          # Migrations
bcrypt==4.2.1            # Password hashing
python-jose[cryptography]==3.3.0  # JWT
pydantic-settings==2.7.0 # Config
```

---

## Modelo de Tenancy

```
SuperAdmin (sistema)
  └── Organization (workspace = tenant)
        ├── User (owner | admin | operator)
        ├── WhatsAppSession (1 por org na V1)
        └── Campaign
              └── Contact
```

**Regra absoluta:** TODA query ao banco filtra `WHERE organization_id = :org_id`.
Nunca há acesso cross-tenant exceto no painel SuperAdmin.

---

## Schema do Banco (PostgreSQL)

### Tabela: `organizations`
```sql
id SERIAL PK
name VARCHAR(200) NOT NULL
slug VARCHAR(80) UNIQUE NOT NULL          -- URL-friendly: "acme-corp"
status VARCHAR(20) DEFAULT 'active'       -- active | suspended | deleted
plan VARCHAR(30) DEFAULT 'free'           -- free | starter | pro | enterprise
max_campaigns INT DEFAULT 0               -- 0 = ilimitado
max_contacts_per_campaign INT DEFAULT 0
max_daily_messages INT DEFAULT 0
max_sessions INT DEFAULT 1
created_at TIMESTAMPTZ DEFAULT NOW()
updated_at TIMESTAMPTZ DEFAULT NOW()
```

### Tabela: `users`
```sql
id SERIAL PK
organization_id INT NOT NULL FK → organizations(id) CASCADE
name VARCHAR(200) NOT NULL
email VARCHAR(255) UNIQUE NOT NULL
password_hash VARCHAR(255) NOT NULL
role VARCHAR(20) NOT NULL DEFAULT 'operator'  -- owner | admin | operator
is_active BOOLEAN DEFAULT true
must_change_password BOOLEAN DEFAULT false    -- forçar troca no 1° login
last_login TIMESTAMPTZ
is_superadmin BOOLEAN DEFAULT false           -- acesso ao painel global /admin
created_at TIMESTAMPTZ DEFAULT NOW()
updated_at TIMESTAMPTZ DEFAULT NOW()
-- Índice: (organization_id, email) para lookup rápido
```

### Tabela: `whatsapp_sessions`
```sql
id SERIAL PK
organization_id INT NOT NULL UNIQUE FK → organizations(id) CASCADE  -- 1 por org na V1
session_key VARCHAR(120) UNIQUE NOT NULL     -- "org-{org.id}" → nome da sessão no bridge
phone_number VARCHAR(30)
status VARCHAR(30) DEFAULT 'not_connected'
  -- not_connected | qr_pending | connected | disconnected | reconnecting | error
qr_code TEXT                                 -- base64 PNG data URL (temporário)
last_seen_at TIMESTAMPTZ
connected_at TIMESTAMPTZ
disconnected_at TIMESTAMPTZ
last_error TEXT
created_at TIMESTAMPTZ DEFAULT NOW()
updated_at TIMESTAMPTZ DEFAULT NOW()
```

### Tabela: `campaigns` (refatorada)
```sql
id SERIAL PK
organization_id INT NOT NULL FK → organizations(id) CASCADE  -- ← NOVO
created_by_user_id INT FK → users(id) SET NULL               -- ← NOVO
name VARCHAR(200) NOT NULL
message_template TEXT NOT NULL DEFAULT 'Oi, {{nome}}'
status VARCHAR(30) DEFAULT 'draft'
  -- draft | ready | running | paused | completed | failed | cancelled
-- Todos os campos operacionais existentes (speed_profile, batch_*, send_window_*, etc.) MANTIDOS
-- Contadores existentes (total_contacts, sent_count, failed_count, etc.) MANTIDOS
scheduled_at TIMESTAMPTZ
started_at TIMESTAMPTZ
finished_at TIMESTAMPTZ
created_at TIMESTAMPTZ DEFAULT NOW()
updated_at TIMESTAMPTZ DEFAULT NOW()
-- Índice: (organization_id, status) para o send engine
```

### Tabela: `contacts` (refatorada)
```sql
-- Manter todos campos existentes +
organization_id INT NOT NULL FK → organizations(id)  -- ← NOVO (desnormalizado para queries)
-- Renomear: phone_raw → phone_original, phone_e164 → phone_normalized
```

### Tabela: `campaign_logs` (substitui `send_logs`)
```sql
id SERIAL PK
campaign_id INT NOT NULL FK → campaigns(id) CASCADE
organization_id INT NOT NULL FK → organizations(id)  -- desnormalizado
contact_id INT FK → contacts(id) SET NULL
event_type VARCHAR(50) NOT NULL
  -- send_attempt | send_success | send_failure | campaign_state | session_event
message TEXT
meta_json JSONB
created_at TIMESTAMPTZ DEFAULT NOW()
-- Índice: (organization_id, campaign_id, created_at DESC)
```

### Tabela: `admin_audit_logs`
```sql
id SERIAL PK
performed_by_user_id INT FK → users(id) SET NULL
action VARCHAR(100) NOT NULL
  -- org.create | org.suspend | user.create | user.disable | campaign.force_stop
target_type VARCHAR(50)
target_id INT
meta_json JSONB
ip_address VARCHAR(45)
created_at TIMESTAMPTZ DEFAULT NOW()
```

---

## Estrutura de Módulos (Nova)

```
mass-sender-saas-vps/
├── main.py                        # App factory, monta todos os routers
├── config.py                      # pydantic-settings: Settings class
├── database.py                    # PostgreSQL engine + SessionLocal (substituído)
│
├── core/
│   ├── auth.py                    # JWT encode/decode, hash_password, verify_password
│   ├── dependencies.py            # get_current_user(), require_roles(), get_org_or_404()
│   ├── middleware.py              # RequestID middleware, audit logging hook
│   └── exceptions.py             # TenantNotFoundError, SessionNotConnectedError, etc.
│
├── models/                        # Um arquivo por entidade (substituem models.py único)
│   ├── __init__.py               # Exporta tudo
│   ├── organization.py
│   ├── user.py
│   ├── whatsapp_session.py
│   ├── campaign.py
│   ├── contact.py
│   ├── campaign_log.py
│   └── audit_log.py
│
├── schemas/                       # Pydantic schemas por domínio
│   ├── auth.py
│   ├── organization.py
│   ├── user.py
│   ├── campaign.py
│   ├── contact.py
│   └── whatsapp.py
│
├── repositories/                  # Camada de acesso ao banco (sempre filtra org_id)
│   ├── base.py                   # BaseRepository com get/list/create/update/delete
│   ├── organization_repo.py
│   ├── user_repo.py
│   ├── campaign_repo.py
│   ├── contact_repo.py
│   └── whatsapp_repo.py
│
├── routers/                       # FastAPI routers por domínio
│   ├── auth.py                   # POST /auth/login, /auth/logout, /auth/refresh
│   ├── admin.py                  # GET|POST /admin/... (SuperAdmin, require_superadmin)
│   ├── organizations.py          # /organizations (dentro do contexto do org admin)
│   ├── users.py                  # /settings/users
│   ├── campaigns.py              # /campaigns e /campaigns/{id}/...
│   ├── contacts.py               # /campaigns/{id}/contacts/...
│   ├── whatsapp.py               # /whatsapp (página e API da sessão)
│   └── dashboard.py              # GET / (dashboard da org)
│
├── services/
│   ├── campaign_service.py       # Refatorado: aceita organization_id em todas funções
│   ├── send_engine.py            # Refatorado: multi-org, cliente por session_key
│   ├── whatsapp_client.py        # Refatorado: parametrizado por session_key
│   └── session_sync.py           # NOVO: sincroniza estado bridge → DB (polling)
│
├── utils/                         # Todos reutilizados sem alteração
│   ├── phone.py
│   ├── csv_parser.py
│   ├── speed_profiles.py
│   ├── schedule_guard.py
│   ├── daily_limit.py
│   └── message_compose.py
│
├── templates/
│   ├── base.html                  # NOVO: layout SaaS com sidebar
│   ├── login.html                 # ATUALIZADO: email + senha
│   ├── change_password.html       # NOVO: troca obrigatória no 1° login
│   ├── dashboard/
│   │   ├── org.html              # Dashboard da organização
│   │   └── admin.html            # Painel SuperAdmin
│   ├── campaigns/
│   │   ├── list.html             # Lista de campanhas
│   │   └── detail.html           # Detalhe da campanha (atual campaign.html)
│   ├── whatsapp/
│   │   └── session.html          # Página de conexão WhatsApp
│   └── settings/
│       └── users.html            # Gerenciamento de usuários da org
│
├── static/
│   ├── styles.css                 # Refatorado: sidebar layout + design SaaS
│   ├── app.js                    # Refatorado: módulos ES
│   ├── dashboard.js               # Polling do dashboard
│   ├── whatsapp.js               # QR + polling de sessão
│   └── admin.js                  # Painel admin
│
├── migrations/                    # Alembic
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 001_initial_schema.py  # Schema completo
│       └── 002_seed_data.py       # Org default + usuário owner
│
├── wa-bridge/
│   ├── server.js                  # REFATORADO: multi-session via SessionManager
│   └── lib/
│       ├── session-manager.js     # NOVO: Map<sessionKey, ClientState>
│       ├── process-guard.js       # Manter
│       └── recipient-resolver.js  # Manter
│
├── alembic.ini
├── docker-compose.yml             # + serviço postgres
├── Dockerfile
├── requirements.txt               # + novas dependências
└── .env.example                   # Documentar todas variáveis
```

---

## Autenticação e RBAC

### Fluxo JWT

```
POST /auth/login { email, password }
  → verifica DB → gera access_token (JWT, 1h) + refresh_token (JWT, 30d)
  → access_token: cookie httponly "access_token" (1h)
  → refresh_token: cookie httponly "refresh_token" (30d)
  → redireciona para /

GET / (qualquer rota protegida)
  → middleware lê cookie access_token → decodifica JWT → injeta CurrentUser
  → se expirado: tenta auto-refresh com refresh_token cookie
  → se refresh inválido: redireciona /auth/login

POST /auth/logout
  → limpa ambos os cookies → redireciona /auth/login
```

**JWT payload:**
```json
{ "sub": "42", "org_id": "7", "role": "admin", "exp": 1234567890 }
```

### Papéis e Permissões

| Ação | owner | admin | operator |
|---|---|---|---|
| Ver campanhas da org | ✅ | ✅ | ✅ |
| Criar/editar campanhas | ✅ | ✅ | ✅ |
| Iniciar/pausar campanhas | ✅ | ✅ | ✅ |
| Gerenciar usuários da org | ✅ | ✅ | ❌ |
| Conectar WhatsApp | ✅ | ✅ | ❌ |
| Excluir organização | ✅ | ❌ | ❌ |
| Acessar /admin (SuperAdmin) | especial | ❌ | ❌ |

**SuperAdmin** é um papel separado (`is_superadmin=True` na tabela `users`), não pertence a nenhuma org específica — tem visão global do sistema.

### Dependency: `get_current_user`
```python
# core/dependencies.py
def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("access_token")
    if not token:
        raise RedirectToLogin()
    payload = decode_jwt(token)  # lança se inválido/expirado
    user = user_repo.get_by_id(db, payload["sub"])
    if not user or not user.is_active:
        raise RedirectToLogin()
    if user.must_change_password and request.url.path != "/auth/change-password":
        raise RedirectToChangePassword()
    return user

def require_roles(*roles: str):
    def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403)
        return user
    return _dep
```

---

## WhatsApp Multi-Sessão (Bridge Refatorado)

### Decisão de Arquitetura

**Um único processo Node.js gerencia N sessões** via `Map<sessionKey, ClientState>`.
Cada organização tem `session_key = "org-{org.id}"`.
Cada sessão abre seu próprio processo Chromium (~200-400MB RAM).
`MAX_SESSIONS` env var controla o limite (default: 50).
Inicialização é **lazy** — Chromium só sobe quando a org conecta o WhatsApp pela primeira vez.

### `wa-bridge/lib/session-manager.js` (NOVO)
```javascript
class SessionManager {
    constructor() {
        this.sessions = new Map();  // sessionKey → { state, client, retryTimer }
        this.maxSessions = parseInt(process.env.MAX_SESSIONS || '50');
    }

    // Lazy init: cria sessão só quando solicitada
    async getOrCreate(sessionKey) { ... }

    // Destroy: fecha Chromium + apaga arquivos de sessão
    async destroy(sessionKey) { ... }

    // Lista estado de todas sessões ativas
    listAll() { ... }
}
```

### Novos endpoints do bridge

| Método | Rota | Propósito |
|---|---|---|
| GET | `/sessions` | Lista todas sessões com status |
| GET | `/sessions/:key` | Estado de uma sessão |
| GET | `/sessions/:key/qr` | QR code da sessão |
| POST | `/sessions/:key/restart` | Reiniciar sessão |
| POST | `/sessions/:key/reset` | Reset completo (apaga arquivos) |
| POST | `/sessions/:key/send-text` | Enviar mensagem via essa sessão |
| DELETE | `/sessions/:key` | Destruir sessão |

**Rotas legadas** (`GET /session`, `POST /messages/send-text`) mantidas usando `WA_SESSION_NAME` como fallback — não quebra ambiente existente durante migração.

### `services/whatsapp_client.py` (refatorado)
```python
class WhatsAppClient:
    def __init__(self, session_key: str):
        self.session_key = session_key
        self.base_url = settings.WA_BRIDGE_BASE_URL

    async def send_text(self, phone_e164: str, message: str) -> dict:
        return await self._post(f"/sessions/{self.session_key}/send-text", ...)

    async def get_session_state(self) -> dict:
        return await self._get(f"/sessions/{self.session_key}")

    async def get_qr(self) -> dict:
        return await self._get(f"/sessions/{self.session_key}/qr")
```

### `services/session_sync.py` (NOVO)

Background task que a cada 10s:
1. Lista todas orgs com sessão ativa no DB
2. Chama `GET /sessions/:key` no bridge para cada uma
3. Atualiza `whatsapp_sessions.status`, `phone_number`, `last_seen_at`, `last_error` no DB
4. Se status mudou para `disconnected` e havia campanha `running` → pausa com motivo `session_disconnected`

### `services/send_engine.py` (refatorado)
```python
class SendEngine:
    _clients: dict[str, WhatsAppClient] = {}

    def _get_client(self, org_id: int) -> WhatsAppClient:
        session = db.query(WhatsAppSession).filter_by(organization_id=org_id).first()
        if not session or session.status != 'connected':
            raise SessionNotConnectedError()
        if session.session_key not in self._clients:
            self._clients[session.session_key] = WhatsAppClient(session.session_key)
        return self._clients[session.session_key]

    async def _process_campaign(self, campaign: Campaign):
        try:
            client = self._get_client(campaign.organization_id)
        except SessionNotConnectedError:
            await pause_campaign(campaign.id, reason='whatsapp_disconnected')
            return
        # ... resto da lógica existente (sem alteração no envio)
```

---

## Rotas das Páginas (HTML)

### Contexto da Organização (usuários logados)
```
GET  /                              → Dashboard da org (stats + campanhas recentes)
GET  /campaigns                     → Lista campanhas
POST /campaigns                     → Criar campanha
GET  /campaigns/{id}                → Detalhe (igual ao atual)
...  /campaigns/{id}/*              → Todos endpoints existentes (+ filtro org_id)
GET  /whatsapp                      → Página de sessão WhatsApp
GET  /whatsapp/qr                   → JSON: QR code atual
POST /whatsapp/restart              → Reiniciar sessão
POST /whatsapp/reset                → Reset completo
GET  /settings/users                → Gerenciar usuários (owner/admin)
POST /settings/users                → Criar usuário
POST /settings/users/{id}/toggle   → Ativar/desativar
POST /settings/users/{id}/reset-pw → Resetar senha
GET  /settings/profile              → Perfil do usuário logado
POST /auth/change-password          → Trocar senha
```

### Painel SuperAdmin (`/admin/*`)
```
GET  /admin                          → Dashboard global
GET  /admin/organizations            → Tabela de orgs
POST /admin/organizations            → Criar organização + usuário owner
GET  /admin/organizations/{id}       → Detalhe da org
POST /admin/organizations/{id}/suspend → Suspender org
DELETE /admin/organizations/{id}    → Excluir org
GET  /admin/stats                    → JSON: métricas globais
GET  /admin/audit-logs              → Log de ações admin
GET  /admin/sessions                 → Estado de todas sessões WA
```

### Auth
```
GET  /auth/login                    → Formulário de login
POST /auth/login                    → Autenticar
POST /auth/logout                   → Sair
POST /auth/refresh                  → Renovar access_token (auto, via JS)
```

---

## Dashboard da Organização (`/`)

**Cards de topo:**
- Status da sessão WhatsApp (badge colorido + número conectado)
- Campanhas ativas agora
- Total enviados (últimos 30 dias)
- Taxa de sucesso (últimos 30 dias)

**Seção: Campanhas recentes** — tabela com status badge, barra de progresso, ações rápidas

**Seção: Atividade recente** — últimas 20 entradas do `campaign_logs` da org

**Polling:** `/api/dashboard/stats` a cada 15s retorna JSON com dados frescos.

---

## Painel SuperAdmin (`/admin`)

**Cards de topo:**
- Total de organizações (ativas / suspensas)
- Organizações com WA conectado agora
- Total de mensagens enviadas hoje
- Taxa média de sucesso global

**Tabela: Organizações** — nome | plano | status WA | campanhas | enviados | falhas | ações

**Tabela: Erros de sessão** — orgs com `status IN ('error', 'disconnected')`

**Top 5 por volume** — orgs que mais enviaram nos últimos 7 dias

**Campanhas recentes** — últimas 10 campanhas em qualquer org

---

## Limites por Plano (estrutura preparada para billing)

```python
# models/organization.py
class Organization(Base):
    plan: str = 'free'
    max_campaigns: int = 0           # 0 = ilimitado
    max_contacts_per_campaign: int = 0
    max_daily_messages: int = 0
    max_sessions: int = 1

# services/campaign_service.py — checar antes de criar campanha
def check_org_limits(org: Organization, db: Session) -> None:
    if org.max_campaigns > 0:
        count = db.query(Campaign).filter_by(organization_id=org.id).count()
        if count >= org.max_campaigns:
            raise LimitExceededError("limite de campanhas atingido")
```

Billing não é implementado agora. A estrutura está pronta para adicionar Stripe Webhooks que atualizem `organization.plan` e os limites correspondentes.

---

## Frontend SaaS (Layout Modernizado)

### `templates/base.html` — Layout base com sidebar
```html
<body class="flex h-screen bg-gray-50">
  <!-- Sidebar -->
  <aside class="w-64 flex flex-col bg-white border-r border-gray-200">
    <div class="logo">Mass Sender</div>
    <nav>
      <a href="/">Dashboard</a>
      <a href="/campaigns">Campanhas</a>
      <a href="/whatsapp">WhatsApp</a>
      <a href="/settings/users">Usuários</a>  <!-- owner/admin only -->
      <a href="/admin">Admin Global</a>       <!-- superadmin only -->
    </nav>
    <div class="user-info">{{ current_user.name }} | {{ current_user.role }}</div>
  </aside>

  <!-- Conteúdo principal -->
  <main class="flex-1 overflow-auto p-8">
    {% block content %}{% endblock %}
  </main>
</body>
```

### Componentes visuais novos
- **Progress bar** de campanha: porcentagem real com animação CSS
- **Status badge** para sessão WA (verde pulsante = conectado, amarelo = QR pendente, vermelho = erro)
- **Toast notifications** melhorados (sucesso / erro / info)
- **Tabelas com hover** e ações inline
- **Onboarding state** — quando org não tem WA conectado, banner call-to-action proeminente
- **Estados vazios** — empty states com ilustração e CTA

---

## Estratégia de Migração (Dados Existentes)

```python
# migrations/versions/002_seed_data.py

# 1. Criar organização default
org = Organization(name="Minha Empresa", slug="minha-empresa", status="active")

# 2. Criar sessão WA para a org (estado inicial: not_connected)
session = WhatsAppSession(
    organization_id=org.id,
    session_key=f"org-{org.id}",
    status="not_connected"
)

# 3. Criar usuário owner a partir da senha atual do .env
owner = User(
    organization_id=org.id,
    name="Admin",
    email=os.getenv("ADMIN_EMAIL", "admin@example.com"),
    password_hash=hash_password(os.getenv("APP_ADMIN_PASSWORD", "admin123")),
    role="owner",
    is_superadmin=True
)

# 4. Vincular campanhas existentes à org default
UPDATE campaigns SET organization_id = {org.id}, created_by_user_id = {owner.id}

# 5. Vincular contacts existentes
UPDATE contacts SET organization_id = {org.id}

# 6. Migrar send_logs → campaign_logs (mapeando campos)
```

**Sessão WA na migração:** Os arquivos `.wwebjs_auth/session-mass-sender/` ficam no volume.
O novo `session_key = "org-1"` buscará `.wwebjs_auth/session-org-1/`.
O usuário precisará escanear o QR novamente — é inevitável (renomear o diretório via script é uma alternativa).

---

## docker-compose.yml (novo serviço)

```yaml
services:
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: mass_sender
      POSTGRES_USER: mass_sender
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - internal
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U mass_sender"]
      interval: 10s
      timeout: 5s
      retries: 5

  wa-bridge:
    # ... igual ao atual (sem mudanças no compose)

  app:
    depends_on:
      postgres:
        condition: service_healthy
      wa-bridge:
        condition: service_started
    environment:
      - DATABASE_URL=postgresql+asyncpg://mass_sender:${POSTGRES_PASSWORD}@postgres:5432/mass_sender
      # DB_PATH removido (não mais SQLite)

volumes:
  postgres_data:   # ← NOVO
  wa_sessions:
  # app_data removido (era o SQLite)
```

---

## Fases de Implementação

### Fase 1 — PostgreSQL + Alembic + Modelos (fundação)
**Arquivos:** `database.py`, `models/`, `migrations/`, `docker-compose.yml`, `requirements.txt`, `config.py`
- Adicionar serviço PostgreSQL ao compose
- Criar `config.py` com pydantic-settings
- Reescrever `database.py` para PostgreSQL (sync para Alembic + async para app)
- Criar todos os modelos em `models/`
- Configurar Alembic + migration 001 (schema completo) + 002 (seed data)
- Verificar: `alembic upgrade head` sem erros, todas tabelas existem no PG

### Fase 2 — Autenticação JWT + RBAC
**Arquivos:** `core/auth.py`, `core/dependencies.py`, `routers/auth.py`, `templates/login.html`, `templates/change_password.html`
- Implementar JWT encode/decode com `python-jose`
- `get_current_user`, `require_roles`, `require_superadmin` como FastAPI dependencies
- Rotas `/auth/login`, `/auth/logout`, `/auth/refresh`, `/auth/change-password`
- Template login com campo email + senha
- Middleware de auto-refresh via cookie

### Fase 3 — Session Manager Multi-Sessão (Bridge)
**Arquivos:** `wa-bridge/lib/session-manager.js`, `wa-bridge/server.js`, `services/whatsapp_client.py`, `services/session_sync.py`
- Criar `SessionManager` no bridge com Map e lazy init
- Refatorar `server.js` para usar SessionManager com rotas `/:sessionKey`
- Manter rotas legacy durante transição
- Atualizar `WhatsAppClient` para aceitar `session_key`
- Criar `session_sync.py` (background task: polling bridge → DB a cada 10s)

### Fase 4 — Multi-Tenant em Campanhas
**Arquivos:** `services/campaign_service.py`, `services/send_engine.py`, `routers/campaigns.py`, `routers/contacts.py`, `repositories/`
- Adicionar `organization_id` a todas as funções do `campaign_service`
- Criar camada `repositories/` (queries sempre filtradas por org_id)
- Refatorar `SendEngine` para resolver cliente por `org_id`
- Verificar sessão conectada antes de iniciar campanha
- Checar limites do plano na criação de campanha

### Fase 5 — Gestão de Usuários e Organizações
**Arquivos:** `routers/users.py`, `routers/organizations.py`, `templates/settings/users.html`
- CRUD de usuários dentro da org (owner/admin only)
- Fluxo de onboarding: primeiro login → troca de senha obrigatória → conectar WA → criar campanha
- Rotas `/settings/users`

### Fase 6 — Painel SuperAdmin
**Arquivos:** `routers/admin.py`, `templates/dashboard/admin.html`, `static/admin.js`
- Dashboard global com métricas do sistema
- CRUD de organizações (criar, suspender, excluir)
- Viewer de audit logs
- Tabela com estado de todas sessões WA

### Fase 7 — Dashboard da Organização
**Arquivos:** `routers/dashboard.py`, `templates/dashboard/org.html`, `static/dashboard.js`
- Stats por org: campanhas, enviados, falhas, taxa de sucesso
- Atividade recente do `campaign_logs`
- Badge de status WhatsApp proeminente com CTA quando desconectado

### Fase 8 — UX/UI SaaS Profissional
**Arquivos:** `templates/base.html`, `static/styles.css`, todos os templates
- Layout sidebar responsivo (desktop + mobile)
- Progress bars reais de campanha com animação
- Badges animados de status WA (pulse verde = conectado)
- Toast system aprimorado
- Estados: loading, empty, error com ilustrações
- Mobile-friendly

### Fase 9 — Observabilidade e Refinamento
**Arquivos:** `core/middleware.py`, `campaign_logs`, rotas de export
- Structured logging por org/campanha/sessão
- Export CSV de falhas por campanha
- Audit log viewer no admin
- Health endpoint detalhado com estado de todas sessões

---

## Arquivos a Criar (Novos)

```
config.py
core/auth.py
core/dependencies.py
core/middleware.py
core/exceptions.py
models/__init__.py
models/organization.py
models/user.py
models/whatsapp_session.py
models/campaign.py
models/contact.py
models/campaign_log.py
models/audit_log.py
schemas/auth.py
schemas/organization.py
schemas/user.py
schemas/campaign.py
schemas/contact.py
schemas/whatsapp.py
repositories/base.py
repositories/organization_repo.py
repositories/user_repo.py
repositories/campaign_repo.py
repositories/contact_repo.py
repositories/whatsapp_repo.py
routers/auth.py
routers/admin.py
routers/organizations.py
routers/users.py
routers/campaigns.py
routers/contacts.py
routers/whatsapp.py
routers/dashboard.py
services/whatsapp_client.py   (substitui services/whatsapp.py)
services/session_sync.py
wa-bridge/lib/session-manager.js
templates/base.html
templates/change_password.html
templates/dashboard/org.html
templates/dashboard/admin.html
templates/whatsapp/session.html
templates/settings/users.html
migrations/env.py
migrations/versions/001_initial_schema.py
migrations/versions/002_seed_data.py
alembic.ini
.env.example
plans/saas-multitenant-evolution.md   (este arquivo)
```

## Arquivos a Modificar (Refatorar)

```
main.py                      → app factory limpo, inclui todos os routers
database.py                  → PostgreSQL engine (substituir SQLite)
models.py                    → dividido em models/ (arquivo pode ser deletado)
requirements.txt             → + novas dependências
docker-compose.yml           → + serviço postgres
wa-bridge/server.js          → multi-session via SessionManager
services/campaign_service.py → + organization_id em todas as funções
services/send_engine.py      → + org routing, verificação de sessão
templates/login.html         → campos email + senha
static/styles.css            → sidebar layout SaaS
static/app.js                → modularizar, atualizar URLs
```

## Arquivos a Reutilizar Sem Alteração

```
utils/phone.py
utils/csv_parser.py
utils/speed_profiles.py
utils/schedule_guard.py
utils/daily_limit.py
utils/message_compose.py
wa-bridge/lib/process-guard.js
wa-bridge/lib/recipient-resolver.js
tests/   (adaptar schemas para novo modelo)
```

---

## Verificação por Fase

| Fase | Critério de Conclusão |
|---|---|
| 1 | `docker compose up` → PG sobe saudável → `alembic upgrade head` sem erros → tabelas existem |
| 2 | POST `/auth/login` → cookies JWT setados → `/` acessível → operator bloqueado de criar usuários |
| 3 | `GET /sessions/org-1` retorna estado → QR aparece → escanear → status vira `connected` no bridge |
| 4 | 2 orgs com sessões diferentes → campanhas em paralelo → logs confirmam session_keys separadas |
| 5 | Owner cria operator → operator loga → não vê "Usuários" no menu → 403 ao acessar `/admin` |
| 6 | SuperAdmin acessa `/admin` → métricas globais corretas → criar/suspender org → audit log registra |
| 7 | Dashboard org mostra stats corretos com polling 15s → badge WA verde ao conectar |
| 8 | Sidebar renderiza em mobile → progress bar atualiza em tempo real → toasts funcionam |
| 9 | Todos eventos logados em `campaign_logs` → export CSV funciona → health detalha sessões |
