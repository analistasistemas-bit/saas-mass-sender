# Plano Final v4.0: SaaS Multi-Tenant — Menor Arquitetura Segura

> **Data:** 2026-03-22
> **Versão:** 4.0 — Baixa Manutenção, Alta Segurança
> **Princípio:** a menor arquitetura que garanta zero vazamento cross-tenant, zero duplicidade
> por concorrência, pause/resume/cancel confiáveis, fila resiliente a restart e restore simples.

---

## Princípios de Decisão

Cada componente desta arquitetura existe porque resolve um dos requisitos de segurança ou
resiliência abaixo. Se não resolve nenhum, não está no V1.

| Requisito | Mecanismo escolhido | Por quê não outro |
|---|---|---|
| Zero vazamento cross-tenant | PostgreSQL RLS + dois roles | Proteção no banco, não só no código |
| Zero duplicidade por concorrência | `SELECT FOR UPDATE SKIP LOCKED` + `job_id` determinístico | Trava no banco antes de enfileirar |
| Pause/cancel confiável | Status check idempotente no início de cada job | Sem remoção no Redis (não confiável) |
| Fila resiliente a restart | Redis + `appendonly yes` | Jobs persistem no volume |
| Sessões isoladas por org | Bridge Node.js multi-session com `session_key = org-{id}` | Um processo, N Chromium |
| Webhooks desacoplados | Fila separada no Redis | Não bloqueia o worker de mensagens |
| Restore simples | Startup recovery automático + pg_dump diário | Sem intervenção manual |

---

## O que NÃO está no V1 (decisão explícita)

| Item | Motivo da exclusão |
|---|---|
| Driver async (asyncpg) | Adiciona complexidade sem ganho real para a escala V1 |
| structlog | `logging` padrão + JSON formatter é suficiente e sem deps extras |
| `human_delay.py` como módulo separado | `random.uniform(min, max)` inline no job |
| Detecção de risco por janela estatística | Contador simples de erros consecutivos é mais previsível |
| Particionamento de tabelas | Desnecessário até ~10M de campaign_logs |
| Múltiplas instâncias worker | 1 worker é suficiente para 10 orgs na V1 |
| Suite de testes completa | Testes críticos incluídos; suite completa é V2 |
| `batch_pause` escalonado a cada 10 batches | `random.uniform` no `batch_pause_min/max` é suficiente |
| Billing / Stripe | Estrutura de campos pronta; integração em V2 |
| RQ Dashboard | Opcional — adicionar após V1 se necessário |

---

## 1. Stack Definitiva V1

| Camada | Tecnologia | Versão |
|---|---|---|
| Backend | FastAPI | 0.115+ |
| ORM | SQLAlchemy 2.0 **sync** (psycopg2) | único driver |
| Banco | PostgreSQL 16 | RLS + JSONB |
| Migrations | Alembic | schema versionado |
| Fila | Redis 7 + RQ | simples e confiável |
| Auth | JWT (access 1h + refresh 30d, httponly cookie) | python-jose |
| Hashing | bcrypt | padrão |
| Config | pydantic-settings | 12-factor |
| Logs | Python `logging` + JSON formatter | sem deps extras |
| Frontend | Jinja2 + Tailwind CSS + Vanilla JS | manter stack |
| Bridge WA | Node.js multi-session | manter wa-bridge |

**`requirements.txt` — adições ao atual:**
```
psycopg2-binary==2.9.10
alembic==1.14.0
bcrypt==4.2.1
python-jose[cryptography]==3.3.0
pydantic-settings==2.7.0
redis==5.2.1
rq==1.16.2
python-json-logger==2.0.7
```

> **Decisão crítica:** SQLAlchemy **sync** em todo o sistema — FastAPI app, workers RQ, Alembic,
> orchestrator, session_sync. Um único engine, um único driver, sem confusão entre sessões async/sync.
> FastAPI suporta handlers sync nativamente via thread pool. A simplicidade operacional compensa.

---

## 2. Banco de Dados

### 2.1 Uma única configuração de engine

```python
# database.py

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session
from contextlib import contextmanager
from config import settings

engine = create_engine(
    settings.DATABASE_URL,            # postgresql+psycopg2://app_user:...@postgres:5432/mass_sender
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,               # detecta conexões mortas automaticamente
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase):
    pass

# Para FastAPI (Depends)
def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Para FastAPI com RLS ativo (tenant routes)
@contextmanager
def get_tenant_db(org_id: int) -> Session:
    db = SessionLocal()
    try:
        db.execute(text(f"SET LOCAL app.current_org = {int(org_id)}"))
        yield db
    finally:
        db.close()

# Para workers RQ e orchestrator (sem RLS — acesso de sistema)
@contextmanager
def get_system_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

`get_tenant_db` usa `SET LOCAL` (scoped à transação, não vaza para o pool).
`get_system_db` usa a conexão sem RLS para o orchestrator e session_sync, que acessam dados de todas as orgs.

### 2.2 Dois roles PostgreSQL (não negociável para segurança)

```sql
-- Role da aplicação (sem BYPASSRLS)
CREATE ROLE app_user LOGIN PASSWORD '${APP_USER_PASSWORD}';
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO app_user;

-- Role admin (BYPASSRLS — usado por Alembic, SuperAdmin, scripts de recovery)
CREATE ROLE app_admin LOGIN PASSWORD '${APP_ADMIN_PASSWORD}' BYPASSRLS;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO app_admin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO app_admin;
```

```env
DATABASE_URL=postgresql+psycopg2://app_user:${APP_USER_PASSWORD}@postgres:5432/mass_sender
DATABASE_URL_ADMIN=postgresql+psycopg2://app_admin:${APP_ADMIN_PASSWORD}@postgres:5432/mass_sender
```

| Contexto | URL | BYPASSRLS |
|---|---|---|
| FastAPI routes de tenant | `DATABASE_URL` | Não — RLS ativo |
| Orchestrator, session_sync | `DATABASE_URL` sem SET LOCAL | Não — acessa todas orgs via `system_db` |
| SuperAdmin routes `/admin/*` | `DATABASE_URL_ADMIN` | Sim |
| Alembic migrations | `DATABASE_URL_ADMIN` | Sim |
| Startup recovery | `DATABASE_URL_ADMIN` | Sim |

> **Nota sobre o orchestrator:** ele usa `get_system_db()` (sem SET LOCAL) com `DATABASE_URL`
> (sem BYPASSRLS). As políticas RLS permitem acesso sem `app.current_org` definido apenas quando
> a policy tem `FORCE ROW LEVEL SECURITY` desativado para o role system — ou simplesmente
> o orchestrator usa `DATABASE_URL_ADMIN`. Decisão mais simples: **orchestrator e session_sync
> usam `DATABASE_URL_ADMIN`** pois precisam ver todas as orgs. Isso é correto e seguro porque
> não são requests de usuários.

### 2.3 Row-Level Security

```sql
-- Ativar em todas as tabelas tenant-scoped
ALTER TABLE campaigns          ENABLE ROW LEVEL SECURITY;
ALTER TABLE contacts           ENABLE ROW LEVEL SECURITY;
ALTER TABLE campaign_logs      ENABLE ROW LEVEL SECURITY;
ALTER TABLE whatsapp_sessions  ENABLE ROW LEVEL SECURITY;
ALTER TABLE users              ENABLE ROW LEVEL SECURITY;
ALTER TABLE organization_webhooks ENABLE ROW LEVEL SECURITY;

-- Policy: visível apenas quando organization_id == configuração da sessão
-- (true) no segundo arg de current_setting evita erro se não estiver definido
CREATE POLICY tenant_isolation ON campaigns
    AS PERMISSIVE FOR ALL TO app_user
    USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::int);

-- Repetir para contacts, campaign_logs, whatsapp_sessions, users, organization_webhooks
```

`organizations` NÃO tem RLS — apenas `app_admin` gerencia orgs. Usuários acessam dados da própria org via outros joins; nunca consultam `organizations` diretamente com app_user.

---

## 3. Schema do Banco

### `organizations`
```sql
id              SERIAL PRIMARY KEY
name            VARCHAR(200) NOT NULL
slug            VARCHAR(80) UNIQUE NOT NULL
status          VARCHAR(20) DEFAULT 'active'       -- active | suspended | deleted
plan            VARCHAR(30) DEFAULT 'free'
max_campaigns   INT DEFAULT 0                       -- 0 = ilimitado
max_contacts_per_campaign INT DEFAULT 0
max_daily_messages INT DEFAULT 0
max_sessions    INT DEFAULT 1
stripe_customer_id        VARCHAR(120)              -- billing futuro (não implementado no V1)
stripe_subscription_id    VARCHAR(120)
trial_ends_at             TIMESTAMPTZ
created_at      TIMESTAMPTZ DEFAULT NOW()
updated_at      TIMESTAMPTZ DEFAULT NOW()
```

### `users`
```sql
id                    SERIAL PRIMARY KEY
organization_id       INT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE
name                  VARCHAR(200) NOT NULL
email                 VARCHAR(255) UNIQUE NOT NULL  -- GLOBAL único (uma pessoa = um email)
password_hash         VARCHAR(255) NOT NULL
role                  VARCHAR(20) NOT NULL DEFAULT 'operator'  -- owner | admin | operator
is_active             BOOLEAN DEFAULT true
must_change_password  BOOLEAN DEFAULT false          -- 1° login: forçar troca
last_login            TIMESTAMPTZ
is_superadmin         BOOLEAN DEFAULT false
created_at            TIMESTAMPTZ DEFAULT NOW()
updated_at            TIMESTAMPTZ DEFAULT NOW()

CREATE INDEX ix_users_org   ON users(organization_id);
CREATE UNIQUE INDEX ix_users_email ON users(email);
```

### `whatsapp_sessions`
```sql
id              SERIAL PRIMARY KEY
organization_id INT NOT NULL UNIQUE REFERENCES organizations(id) ON DELETE CASCADE
session_key     VARCHAR(120) UNIQUE NOT NULL   -- "org-{id}"
phone_number    VARCHAR(30)
status          VARCHAR(30) DEFAULT 'not_connected'
  -- not_connected | qr_pending | connected | disconnected | reconnecting | error
qr_code         TEXT                            -- base64 PNG; limpar após conexão estabelecida
last_seen_at    TIMESTAMPTZ
connected_at    TIMESTAMPTZ
disconnected_at TIMESTAMPTZ
last_error      TEXT

-- Anti-ban por sessão
daily_sent_count   INT DEFAULT 0
daily_sent_date    DATE
warmup_daily_limit INT DEFAULT 50               -- atualizado diariamente
session_paused_until TIMESTAMPTZ               -- pausa automática anti-ban

created_at      TIMESTAMPTZ DEFAULT NOW()
updated_at      TIMESTAMPTZ DEFAULT NOW()

CREATE INDEX ix_wa_sessions_status ON whatsapp_sessions(status);
```

### `campaigns`
```sql
id                  SERIAL PRIMARY KEY
organization_id     INT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE
created_by_user_id  INT REFERENCES users(id) ON DELETE SET NULL
name                VARCHAR(200) NOT NULL
message_template    TEXT NOT NULL DEFAULT 'Oi, {{nome}}'
extra_templates     JSONB DEFAULT '[]'            -- variações anti-ban: [{"template": "..."}]
status              VARCHAR(30) DEFAULT 'draft'
  -- draft | ready | running | paused | completed | failed | cancelled

-- Orquestração sem sleep: o orchestrator só processa quando next_batch_at <= NOW()
next_batch_at       TIMESTAMPTZ DEFAULT NOW()

-- Configurações operacionais (mantidas do sistema atual)
speed_profile                    VARCHAR(30) DEFAULT 'conservative'
send_delay_min_seconds           INT DEFAULT 5
send_delay_max_seconds           INT DEFAULT 10
batch_pause_min_seconds          INT DEFAULT 5
batch_pause_max_seconds          INT DEFAULT 10
batch_size_initial               INT DEFAULT 10
batch_size_max                   INT DEFAULT 25
batch_growth_step                INT DEFAULT 2
batch_growth_streak_required     INT DEFAULT 3
batch_shrink_step                INT DEFAULT 2
batch_shrink_error_streak_required INT DEFAULT 2
batch_size_floor                 INT DEFAULT 5
send_window_start_hour           INT DEFAULT 8
send_window_end_hour             INT DEFAULT 20
daily_limit                      INT DEFAULT 0
sent_today                       INT DEFAULT 0
last_send_date                   DATE
pause_reason                     VARCHAR(200)

-- Contadores
total_contacts      INT DEFAULT 0
valid_contacts      INT DEFAULT 0
invalid_contacts    INT DEFAULT 0
sent_count          INT DEFAULT 0
failed_count        INT DEFAULT 0
pending_count       INT DEFAULT 0

scheduled_at        TIMESTAMPTZ
started_at          TIMESTAMPTZ
finished_at         TIMESTAMPTZ
created_at          TIMESTAMPTZ DEFAULT NOW()
updated_at          TIMESTAMPTZ DEFAULT NOW()

CREATE INDEX ix_campaigns_org_status  ON campaigns(organization_id, status);
CREATE INDEX ix_campaigns_next_batch  ON campaigns(next_batch_at) WHERE status = 'running';
```

### `contacts`
```sql
id               SERIAL PRIMARY KEY
campaign_id      INT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE
organization_id  INT NOT NULL REFERENCES organizations(id)
name             VARCHAR(200) DEFAULT ''
phone_original   VARCHAR(50) NOT NULL
phone_normalized VARCHAR(30)
email            VARCHAR(255) DEFAULT ''
source           VARCHAR(20) DEFAULT 'csv'
status           VARCHAR(20) DEFAULT 'pending'
  -- pending | processing | sent | failed | invalid
error_message    TEXT
attempt_count    INT DEFAULT 0

-- Controle de concorrência e recovery
rq_job_id        VARCHAR(100)       -- ID do job RQ; evita enfileirar duplicata
processing_since TIMESTAMPTZ        -- quando entrou em 'processing'; detecta stale jobs

last_attempt_at  TIMESTAMPTZ
sent_at          TIMESTAMPTZ
created_at       TIMESTAMPTZ DEFAULT NOW()
updated_at       TIMESTAMPTZ DEFAULT NOW()

CREATE INDEX ix_contacts_campaign_status ON contacts(campaign_id, status);
CREATE INDEX ix_contacts_stale ON contacts(status, processing_since)
    WHERE status = 'processing';     -- para recovery periódico

UNIQUE (campaign_id, phone_normalized);
```

### `campaign_logs`
```sql
id              SERIAL PRIMARY KEY
campaign_id     INT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE
organization_id INT NOT NULL REFERENCES organizations(id)
contact_id      INT REFERENCES contacts(id) ON DELETE SET NULL
event_type      VARCHAR(50) NOT NULL
  -- send_attempt | send_success | send_failure | send_retry
  -- campaign_state | session_event | queue_event | recovery_event
message         TEXT
meta_json       JSONB
created_at      TIMESTAMPTZ DEFAULT NOW()

CREATE INDEX ix_logs_org_campaign ON campaign_logs(organization_id, campaign_id);
CREATE INDEX ix_logs_created      ON campaign_logs(created_at DESC);
```

### `admin_audit_logs`
```sql
id                   SERIAL PRIMARY KEY
performed_by_user_id INT REFERENCES users(id) ON DELETE SET NULL
action               VARCHAR(100) NOT NULL
target_type          VARCHAR(50)
target_id            INT
meta_json            JSONB
ip_address           VARCHAR(45)
created_at           TIMESTAMPTZ DEFAULT NOW()

CREATE INDEX ix_audit_created ON admin_audit_logs(created_at DESC);
```

### `organization_webhooks`
```sql
id              SERIAL PRIMARY KEY
organization_id INT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE
url             VARCHAR(500) NOT NULL
secret          VARCHAR(120) NOT NULL    -- HMAC signing key
events          JSONB NOT NULL           -- ["campaign.completed", "message.failed", ...]
is_active       BOOLEAN DEFAULT true
created_at      TIMESTAMPTZ DEFAULT NOW()
updated_at      TIMESTAMPTZ DEFAULT NOW()
```

---

## 4. Fila: Redis + RQ

### 4.1 Por que Redis + RQ

- RQ persiste jobs no Redis; com `appendonly yes`, jobs sobrevivem a restart
- `job_id` determinístico garante deduplicação nativa
- Zero configuração extra para retry
- Dashboard opcional (rq-dashboard) sem alterar a arquitetura

### 4.2 Filas

```python
# queue/queues.py
from redis import Redis
from rq import Queue
from config import settings

redis_conn = Redis.from_url(settings.REDIS_URL)

high_queue    = Queue('high',     connection=redis_conn)  # testes, ações urgentes
default_queue = Queue('default',  connection=redis_conn)  # envio normal de campanhas
low_queue     = Queue('low',      connection=redis_conn)  # retry de mensagens falhas
webhook_queue = Queue('webhooks', connection=redis_conn)  # entrega de webhooks
```

### 4.3 Job de envio (idempotente)

```python
# queue/jobs.py

def send_message_job(contact_id: int, campaign_id: int, organization_id: int) -> None:
    """
    Idempotente por design:
    - job_id determinístico evita duplicata na fila
    - status check no início evita envio se job foi cancelado/pausado
    """
    with get_tenant_db_sync(organization_id) as db:
        contact = db.get(Contact, contact_id)

        # ─── Guard de idempotência ──────────────────────────────────────────
        if contact is None or contact.status != 'processing':
            return  # job obsoleto (pausa, cancel ou duplicata)

        campaign = db.get(Campaign, campaign_id)
        if campaign.status not in ('running',):
            # Campanha não está mais running: devolve contato para pending
            contact.status = 'pending'
            contact.rq_job_id = None
            db.commit()
            return

        # ─── Verificar sessão ───────────────────────────────────────────────
        session = db.query(WhatsAppSession).filter_by(
            organization_id=organization_id
        ).first()
        if not session or session.status != 'connected':
            _pause_campaign(db, campaign, reason='session_disconnected')
            contact.status = 'pending'
            db.commit()
            return

        # ─── Verificar limite anti-ban da sessão ────────────────────────────
        if not _session_allows_send(db, session):
            contact.status = 'pending'
            db.commit()
            return

        # ─── Enviar ─────────────────────────────────────────────────────────
        message = _render_message(campaign, contact)
        client = WhatsAppClient(session.session_key)
        try:
            client.send_text(contact.phone_normalized, message)
            contact.status = 'sent'
            contact.sent_at = utcnow()
            session.daily_sent_count += 1
            _log(db, 'send_success', campaign_id, contact_id, organization_id)
            _fire_webhook(organization_id, 'message.sent', {...})
        except TemporaryError as e:
            contact.attempt_count += 1
            if contact.attempt_count < 3:
                contact.status = 'pending'   # volta para pending; orchestrator re-enfileira
                contact.rq_job_id = None
                _log(db, 'send_retry', campaign_id, contact_id, organization_id,
                     meta={'attempt': contact.attempt_count, 'error': str(e)})
            else:
                contact.status = 'failed'
                contact.error_message = str(e)
                _log(db, 'send_failure', ...)
                _fire_webhook(organization_id, 'message.failed', {...})
        except PermanentError as e:
            contact.status = 'failed'
            contact.error_message = str(e)
            _log(db, 'send_failure', ...)
        finally:
            contact.last_attempt_at = utcnow()
            contact.processing_since = None
            db.commit()
```

> **Retry por `pending`:** quando um envio temporário falha e `attempt_count < 3`, o contato
> volta para `pending`. O orchestrator o reenfileirará no próximo tick com delay natural do
> `next_batch_at`. Isso é mais simples e previsível do que gerenciar delays de retry no RQ.
> Exceção: erros 429 (rate limit) — nesse caso o orchestrator verifica o erro consecutivo e
> pausa a sessão por 30 minutos.

### 4.4 Job de webhook (desacoplado)

```python
def deliver_webhook_job(org_id: int, event: str, payload: dict) -> None:
    """Separado do send_message_job. Falha de webhook não afeta envio."""
    with get_system_db() as db:
        webhooks = db.query(OrganizationWebhook).filter_by(
            organization_id=org_id, is_active=True
        ).all()
        for wh in webhooks:
            if event not in wh.events:
                continue
            body = json.dumps({"event": event, "data": payload, "ts": utcnow().isoformat()})
            sig = hmac.new(wh.secret.encode(), body.encode(), hashlib.sha256).hexdigest()
            resp = httpx.post(wh.url, content=body,
                headers={"X-Webhook-Signature": sig, "Content-Type": "application/json"},
                timeout=10.0)
            resp.raise_for_status()  # força retry do RQ (max 3 tentativas)

def _fire_webhook(org_id: int, event: str, payload: dict) -> None:
    """Chamado de dentro de send_message_job — apenas enfileira, não bloqueia."""
    webhook_queue.enqueue(
        deliver_webhook_job,
        kwargs={'org_id': org_id, 'event': event, 'payload': payload},
        job_timeout=30,
        retry=Retry(max=3, interval=[60, 300, 900]),
    )
```

### 4.5 Worker único

```python
# workers/message_worker.py
from rq import Worker
from queue.queues import redis_conn, high_queue, default_queue, low_queue, webhook_queue

if __name__ == '__main__':
    Worker(
        [high_queue, default_queue, low_queue, webhook_queue],
        connection=redis_conn
    ).work()
```

Um único worker consome todas as filas por prioridade. Para escalar: adicionar instâncias `worker` no compose (stateless).

---

## 5. Orchestrator sem Sleep

### 5.1 Loop baseado em `next_batch_at`

```python
# services/campaign_orchestrator.py
import threading, time, random
from datetime import datetime, timezone, timedelta

class CampaignOrchestrator:
    def run_forever(self):
        """Executado em thread de background (daemon=True)."""
        while True:
            try:
                self._tick()
            except Exception as e:
                log.error(f"orchestrator_tick_error: {e}")
            time.sleep(2)  # tick leve; não bloqueia nenhuma campanha específica

    def _tick(self):
        """Processa apenas campanhas cujo next_batch_at já chegou."""
        with get_system_db() as db:
            now = datetime.now(timezone.utc)
            campaigns = db.execute(
                select(Campaign)
                .where(Campaign.status == 'running', Campaign.next_batch_at <= now)
                .with_for_update(skip_locked=True)   # multi-process safe
                .limit(20)                            # processa até 20 por tick
            ).scalars().all()

            for campaign in campaigns:
                self._process_campaign(db, campaign)
            db.commit()

    def _process_campaign(self, db: Session, campaign: Campaign) -> None:
        # 1. Verificar janela de envio
        if not is_within_send_window(campaign):
            campaign.next_batch_at = _next_window_open(campaign)
            return

        # 2. Verificar limite diário da campanha
        if daily_limit_reached(campaign):
            campaign.next_batch_at = _midnight_plus_buffer()
            return

        # 3. Verificar sessão (via DB — session_sync atualizou)
        session = db.query(WhatsAppSession).filter_by(
            organization_id=campaign.organization_id
        ).first()
        if not session or session.status != 'connected':
            _pause_campaign(db, campaign, reason='session_disconnected')
            return

        # 4. Verificar pausa anti-ban da sessão
        if session.session_paused_until and utcnow() < session.session_paused_until:
            campaign.next_batch_at = session.session_paused_until
            return

        # 5. Buscar e travar contatos pending
        contacts = self._fetch_and_lock(db, campaign)
        if not contacts:
            _complete_campaign(db, campaign)
            return

        # 6. Enfileirar jobs
        for contact in contacts:
            contact.status = 'processing'
            contact.processing_since = utcnow()
            job = default_queue.enqueue(
                send_message_job,
                kwargs={
                    'contact_id': contact.id,
                    'campaign_id': campaign.id,
                    'organization_id': campaign.organization_id,
                },
                job_id=f"send-{contact.id}",      # determinístico = idempotente
                job_timeout=300,
            )
            contact.rq_job_id = job.id

        # 7. Agendar próximo batch (sem sleep)
        pause_s = random.randint(
            campaign.batch_pause_min_seconds,
            campaign.batch_pause_max_seconds
        )
        campaign.next_batch_at = utcnow() + timedelta(seconds=pause_s)

    def _fetch_and_lock(self, db: Session, campaign: Campaign) -> list[Contact]:
        return db.execute(
            select(Contact)
            .where(Contact.campaign_id == campaign.id, Contact.status == 'pending')
            .limit(campaign.batch_size_initial)
            .with_for_update(skip_locked=True)    # zero duplicidade por concorrência
        ).scalars().all()
```

**`next_batch_at` por situação:**

| Situação | `next_batch_at` definido como |
|---|---|
| Campanha iniciada | `NOW()` (imediato) |
| Após batch normal | `NOW() + random(batch_pause_min, batch_pause_max)` |
| Fora da janela de envio | `datetime de send_window_start_hour` |
| Limite diário atingido | meia-noite + 5 min |
| Sessão pausada por anti-ban | `session.session_paused_until` |
| Campanha pausada/cancelada | irrelevante (status != running) |

---

## 6. Pause / Resume / Cancel (garantidos)

```python
# services/campaign_service.py

def pause_campaign(db: Session, campaign_id: int, reason: str) -> None:
    campaign = db.get(Campaign, campaign_id)
    campaign.status = 'paused'
    campaign.pause_reason = reason
    # Devolver contatos 'processing' para 'pending' (jobs que executarem vão sair no guard)
    db.execute(
        update(Contact)
        .where(Contact.campaign_id == campaign_id, Contact.status == 'processing')
        .values(status='pending', rq_job_id=None, processing_since=None)
    )
    db.commit()

def resume_campaign(db: Session, campaign_id: int) -> None:
    campaign = db.get(Campaign, campaign_id)
    campaign.status = 'running'
    campaign.pause_reason = None
    campaign.next_batch_at = utcnow()   # processa imediatamente no próximo tick
    db.commit()

def cancel_campaign(db: Session, campaign_id: int) -> None:
    campaign = db.get(Campaign, campaign_id)
    campaign.status = 'cancelled'
    # Fechar contatos abertos (jobs que executarem vão ver status != 'processing' e sair)
    db.execute(
        update(Contact)
        .where(
            Contact.campaign_id == campaign_id,
            Contact.status.in_(['pending', 'processing'])
        )
        .values(status='failed', error_message='campanha cancelada', rq_job_id=None)
    )
    db.commit()
```

**Garantia:** qualquer job ainda na fila Redis ao executar encontrará `contact.status != 'processing'` e retornará silenciosamente sem enviar.

---

## 7. Anti-Ban Simplificado

### 7.1 Três mecanismos — sem sofisticação desnecessária

**1. Warm-up por dias de conexão** (tabela estática, sem cálculo):

```python
# utils/warmup.py
WARMUP_SCHEDULE = {0: 50, 1: 100, 2: 200, 3: 350, 4: 500, 7: 750, 14: 1000, 30: 2000}

def get_warmup_limit(connected_at: datetime) -> int:
    days = (utcnow() - connected_at).days
    return next(
        (limit for threshold, limit in sorted(WARMUP_SCHEDULE.items(), reverse=True)
         if days >= threshold),
        50
    )
```

**2. Limite de sessão diário** (contagem simples no job):

```python
# utils/warmup.py (continuação)

def session_allows_send(session: WhatsAppSession) -> bool:
    today = date.today()
    if session.daily_sent_date != today:
        return True   # contador vai resetar no próximo envio
    if session.warmup_daily_limit > 0 and session.daily_sent_count >= session.warmup_daily_limit:
        return False  # limite do dia atingido
    if session.session_paused_until and utcnow() < session.session_paused_until:
        return False  # pausa ativa
    return True
```

**3. Detecção simples de erros consecutivos** (sem janela estatística):

No `send_message_job`, após um erro de envio:

```python
# Contar erros consecutivos da sessão nos últimos 10 minutos
recent_errors = db.query(func.count(CampaignLog.id)).filter(
    CampaignLog.organization_id == organization_id,
    CampaignLog.event_type == 'send_failure',
    CampaignLog.created_at >= utcnow() - timedelta(minutes=10)
).scalar()

if recent_errors >= 5:
    session.session_paused_until = utcnow() + timedelta(minutes=30)
    _pause_all_org_campaigns(db, organization_id, reason='consecutive_errors')
    db.commit()
```

**4. Variação de templates** (anti-fingerprint, inline):

```python
# utils/message_compose.py (atualizado)
def render_campaign_message(campaign, contact) -> str:
    templates = [campaign.message_template]
    if campaign.extra_templates:
        templates += [t['template'] for t in campaign.extra_templates]
    chosen = random.choice(templates)
    return chosen.replace('{{nome}}', contact.name or 'amigo')
```

**5. Delay entre mensagens** (inline no job, sem módulo separado):

```python
# dentro de send_message_job, após envio bem-sucedido:
time.sleep(random.uniform(
    campaign.send_delay_min_seconds,
    campaign.send_delay_max_seconds
))
```

---

## 8. Session Manager WhatsApp

### 8.1 Bridge multi-sessão (wa-bridge refatorado)

```javascript
// wa-bridge/lib/session-manager.js
class SessionManager {
    constructor() {
        this.sessions = new Map();   // sessionKey → { state, client }
        this.maxSessions = parseInt(process.env.MAX_SESSIONS || '10');
    }

    async getOrCreate(sessionKey) {
        if (this.sessions.has(sessionKey)) return this.sessions.get(sessionKey);

        const active = [...this.sessions.values()].filter(
            s => ['qr_pending', 'connected', 'reconnecting'].includes(s.state.status)
        ).length;

        if (active >= this.maxSessions) {
            throw Object.assign(new Error('MAX_SESSIONS_REACHED'), { code: 'MAX_SESSIONS_REACHED' });
        }

        const state = this._createState();
        this.sessions.set(sessionKey, { state, client: null });
        await this._initClient(sessionKey);
        return this.sessions.get(sessionKey);
    }

    async destroy(sessionKey) {
        const session = this.sessions.get(sessionKey);
        if (!session) return;
        if (session.client) await session.client.destroy().catch(() => {});
        await fs.rm(`${dataPath}/session-${sessionKey}`, { recursive: true, force: true }).catch(() => {});
        this.sessions.delete(sessionKey);
    }

    listAll() {
        return [...this.sessions.entries()].map(([key, s]) => ({
            sessionKey: key,
            status: s.state.status,
            connected: s.state.connected,
            phone: s.state.phone,
            lastError: s.state.lastError,
        }));
    }
}
```

### 8.2 Endpoints do bridge

| Método | Rota | Propósito |
|---|---|---|
| GET | `/sessions` | Lista todas sessões ativas |
| GET | `/sessions/:key` | Estado de uma sessão |
| GET | `/sessions/:key/qr` | QR code (404 se não pendente) |
| POST | `/sessions/:key/start` | Iniciar sessão (lazy) |
| POST | `/sessions/:key/restart` | Reiniciar |
| POST | `/sessions/:key/reset` | Reset + apagar arquivos |
| POST | `/sessions/:key/send-text` | Enviar mensagem |
| DELETE | `/sessions/:key` | Destruir sessão |
| GET | `/health` | Saúde geral |

Rotas legadas (`GET /session`, `POST /messages/send-text`) mantidas durante migração.

### 8.3 `session_sync.py` — polling simples

```python
# services/session_sync.py
import threading, time

def run_forever():
    """Executado em thread de background."""
    while True:
        try:
            _sync_all_sessions()
            _update_warmup_limits()
            _recover_stale_contacts()
        except Exception as e:
            log.error(f"session_sync_error: {e}")
        time.sleep(10)

def _sync_all_sessions():
    with get_system_db() as db:
        sessions = db.query(WhatsAppSession).all()
        for session in sessions:
            try:
                state = WhatsAppClient(session.session_key).get_session_state()
                old_status = session.status
                session.status = state['state']
                session.phone_number = state.get('phone')
                session.last_seen_at = utcnow()
                if state.get('lastError'):
                    session.last_error = state['lastError']

                if old_status == 'connected' and session.status == 'disconnected':
                    _pause_all_org_campaigns(db, session.organization_id, 'session_disconnected')
                    _fire_webhook(session.organization_id, 'session.disconnected', {})
            except Exception as e:
                log.warning(f"session_poll_error: {session.session_key}: {e}")
        db.commit()

def _update_warmup_limits():
    with get_system_db() as db:
        sessions = db.query(WhatsAppSession).filter(
            WhatsAppSession.connected_at.isnot(None)
        ).all()
        for session in sessions:
            session.warmup_daily_limit = get_warmup_limit(session.connected_at)
        db.commit()

def _recover_stale_contacts():
    """Contatos em 'processing' há mais de 5 minutos → devolver para 'pending'."""
    cutoff = utcnow() - timedelta(minutes=5)
    with get_system_db() as db:
        recovered = db.execute(
            update(Contact)
            .where(Contact.status == 'processing', Contact.processing_since < cutoff)
            .values(status='pending', rq_job_id=None, processing_since=None)
            .returning(Contact.id)
        ).fetchall()
        if recovered:
            log.warning(f"recovery_stale_contacts: {len(recovered)} contacts recovered")
        db.commit()
```

---

## 9. Startup Recovery

```python
# main.py — lifespan

@contextmanager
def lifespan(app: FastAPI):
    # 1. Recovery antes de iniciar qualquer processamento
    _startup_recovery()

    # 2. Iniciar orchestrator e session_sync em threads de background
    orchestrator_thread = threading.Thread(
        target=orchestrator.run_forever, daemon=True, name="orchestrator"
    )
    sync_thread = threading.Thread(
        target=session_sync.run_forever, daemon=True, name="session_sync"
    )
    orchestrator_thread.start()
    sync_thread.start()

    yield   # app rodando

    # Shutdown: threads daemon encerram automaticamente

def _startup_recovery():
    """Corrige estados inconsistentes ANTES de iniciar o orchestrator."""
    log.info("startup_recovery_starting")
    with get_system_db() as db:
        # 1. Contatos presos em 'processing' (job morreu) → pending
        result = db.execute(
            update(Contact)
            .where(Contact.status == 'processing')
            .values(status='pending', rq_job_id=None, processing_since=None)
            .returning(Contact.id)
        ).fetchall()

        # 2. next_batch_at muito atrasado → resetar para agora
        db.execute(
            update(Campaign)
            .where(
                Campaign.status == 'running',
                Campaign.next_batch_at < utcnow() - timedelta(hours=1)
            )
            .values(next_batch_at=utcnow())
        )
        db.commit()

    count = len(result)
    if count:
        log.warning(f"startup_recovery: {count} stale contacts recovered to pending")
    log.info("startup_recovery_complete")
```

---

## 10. Autenticação e RBAC

### Fluxo JWT

```
POST /auth/login { email, password }
  → busca por email → bcrypt.checkpw → gera access_token (1h) + refresh_token (30d)
  → ambos em cookies httponly → redireciona /

Qualquer rota protegida
  → decodifica cookie access_token → injeta CurrentUser
  → se expirado: auto-refresh com refresh_token cookie
  → se refresh inválido: redireciona /auth/login

POST /auth/logout → limpa ambos os cookies
```

**JWT payload:**
```json
{ "sub": "42", "org_id": 7, "role": "admin", "is_superadmin": false, "exp": 1234567890 }
```

### Middleware RLS

```python
# core/middleware.py
class TenantContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Injeta org_id no request.state para uso por get_tenant_db
        token = request.cookies.get("access_token")
        if token:
            try:
                payload = decode_jwt(token)
                request.state.org_id = payload.get("org_id")
                request.state.is_superadmin = payload.get("is_superadmin", False)
            except Exception:
                request.state.org_id = None
        return await call_next(request)
```

### RBAC

| Ação | owner | admin | operator |
|---|---|---|---|
| Ver/criar/editar campanhas | ✅ | ✅ | ✅ |
| Iniciar/pausar campanhas | ✅ | ✅ | ✅ |
| Gerenciar usuários da org | ✅ | ✅ | ❌ |
| Conectar WhatsApp | ✅ | ✅ | ❌ |
| Configurar webhooks | ✅ | ✅ | ❌ |
| Excluir organização | ✅ | ❌ | ❌ |
| Acessar `/admin` | superadmin | ❌ | ❌ |

---

## 11. Logs (Simples e Estruturado)

```python
# core/logging.py
import logging
from pythonjsonlogger import jsonlogger

def configure_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(jsonlogger.JsonFormatter(
        '%(asctime)s %(levelname)s %(name)s %(message)s'
    ))
    logging.root.setLevel(logging.INFO)
    logging.root.handlers = [handler]

# Uso em qualquer módulo:
log = logging.getLogger(__name__)
log.info("send_success", extra={
    "organization_id": 3,
    "campaign_id": 56,
    "contact_id": 1234,
    "session_key": "org-3",
})
```

Saída JSON coletável por qualquer stack de observabilidade (Loki, CloudWatch, etc.) sem dependência extra além de `python-json-logger`.

---

## 12. Estrutura de Módulos

```
mass-sender-saas-vps/
│
├── main.py                          # app factory + lifespan (recovery + threads)
├── config.py                        # pydantic-settings: DATABASE_URL, REDIS_URL, JWT_SECRET...
├── database.py                      # engine único psycopg2 + get_db, get_tenant_db, get_system_db
│
├── core/
│   ├── auth.py                      # JWT encode/decode, bcrypt
│   ├── dependencies.py              # get_current_user, require_roles, require_superadmin
│   ├── middleware.py                # TenantContextMiddleware (injeta org_id)
│   ├── exceptions.py               # LimitExceededError, SessionNotConnectedError
│   └── logging.py                  # configure_logging() com python-json-logger
│
├── models/
│   ├── __init__.py
│   ├── organization.py
│   ├── user.py
│   ├── whatsapp_session.py          # + daily_sent_count, warmup_daily_limit, session_paused_until
│   ├── campaign.py                  # + next_batch_at, extra_templates
│   ├── contact.py                   # + rq_job_id, processing_since
│   ├── campaign_log.py
│   ├── audit_log.py
│   └── organization_webhook.py
│
├── schemas/
│   ├── auth.py, organization.py, user.py, campaign.py, contact.py, whatsapp.py, webhook.py
│
├── repositories/                    # queries filtradas por organization_id
│   ├── base.py, organization_repo.py, user_repo.py
│   ├── campaign_repo.py, contact_repo.py, whatsapp_repo.py
│
├── routers/
│   ├── auth.py                      # /auth/login, /logout, /refresh, /change-password
│   ├── admin.py                    # /admin/* com DATABASE_URL_ADMIN
│   ├── dashboard.py                # GET /
│   ├── organizations.py
│   ├── users.py                    # /settings/users
│   ├── campaigns.py                # /campaigns e /campaigns/{id}/*
│   ├── contacts.py
│   ├── whatsapp.py                 # /whatsapp/*
│   └── webhooks.py                 # /settings/webhooks
│
├── services/
│   ├── campaign_orchestrator.py    # loop next_batch_at + SELECT FOR UPDATE SKIP LOCKED
│   ├── campaign_service.py         # CRUD multi-tenant + pause/resume/cancel
│   ├── whatsapp_client.py          # HTTP client por session_key
│   ├── session_sync.py             # thread: sync bridge→DB + warmup + stale recovery
│   ├── webhook_service.py          # _fire_webhook → enfileira deliver_webhook_job
│   └── limits_service.py           # check plano
│
├── queue/
│   ├── queues.py                   # high, default, low, webhooks
│   ├── jobs.py                     # send_message_job (idempotente), deliver_webhook_job
│   └── retry.py                    # RetryPolicy, classify_error (sem exponential backoff externo)
│
├── workers/
│   └── message_worker.py           # Worker RQ (consome todas as filas)
│
├── utils/
│   ├── phone.py                    # manter sem alteração
│   ├── csv_parser.py               # manter
│   ├── speed_profiles.py           # manter
│   ├── schedule_guard.py           # manter
│   ├── daily_limit.py              # manter
│   ├── message_compose.py          # + suporte a extra_templates (random.choice)
│   └── warmup.py                   # NOVO: tabela estática + get_warmup_limit + session_allows_send
│
├── templates/
│   ├── base.html                   # sidebar layout SaaS
│   ├── login.html, change_password.html
│   ├── dashboard/org.html, dashboard/admin.html
│   ├── campaigns/list.html, campaigns/detail.html
│   ├── whatsapp/session.html
│   └── settings/users.html, settings/webhooks.html
│
├── static/
│   ├── styles.css, app.js, dashboard.js, whatsapp.js, admin.js
│
├── migrations/
│   ├── env.py                      # usa DATABASE_URL_ADMIN
│   └── versions/
│       ├── 001_initial_schema.py   # schema + roles + RLS + índices
│       └── 002_seed_data.py        # org default + owner + sessão WA
│
├── tests/
│   ├── test_rls.py                 # CRÍTICO: cross-tenant bloqueado
│   ├── test_job_idempotency.py     # CRÍTICO: duplicata não envia duas vezes
│   ├── test_pause_cancel.py        # CRÍTICO: jobs na fila respeitam pausa/cancel
│   └── conftest.py                 # fixtures: DB, fakeredis, factory_boy
│
├── wa-bridge/
│   ├── server.js                   # refatorado: usa SessionManager
│   └── lib/
│       ├── session-manager.js      # NOVO: Map + lazy init + MAX_SESSIONS
│       ├── process-guard.js        # manter
│       └── recipient-resolver.js   # manter
│
├── alembic.ini
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── requirements-dev.txt            # pytest, fakeredis, factory_boy
└── .env.example
```

---

## 13. Docker Compose

```yaml
services:
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: mass_sender
      POSTGRES_USER: mass_sender        # role owner — cria app_user e app_admin via migration
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks: [internal]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U mass_sender"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: redis-server --appendonly yes --maxmemory 256mb --maxmemory-policy noeviction
    volumes:
      - redis_data:/data
    networks: [internal]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  wa-bridge:
    build: ./wa-bridge
    restart: unless-stopped
    env_file: .env
    environment:
      - WA_BRIDGE_HOST=0.0.0.0
      - MAX_SESSIONS=10
    volumes:
      - wa_sessions:/app/.wwebjs_auth
    networks: [internal]
    shm_size: 4gb
    security_opt: [seccomp=unconfined]

  app:
    build: .
    restart: unless-stopped
    env_file: .env
    ports: ["127.0.0.1:8000:8000"]
    depends_on:
      postgres: {condition: service_healthy}
      redis: {condition: service_healthy}
      wa-bridge: {condition: service_started}
    networks: [internal]

  worker:
    build: .
    command: python -m workers.message_worker
    restart: unless-stopped
    env_file: .env
    depends_on:
      postgres: {condition: service_healthy}
      redis: {condition: service_healthy}
      wa-bridge: {condition: service_started}
    networks: [internal]

volumes:
  postgres_data:
  redis_data:
  wa_sessions:

networks:
  internal: {driver: bridge}
```

> `maxmemory-policy noeviction` no Redis: jobs nunca são descartados silenciosamente por pressão
> de memória. Se Redis encher (improvável com 256MB), retorna erro — melhor do que perder jobs.

---

## 14. Rotas

### Tenant (usuários logados)
```
GET  /                              Dashboard da org
GET  /campaigns                     Lista campanhas
POST /campaigns                     Criar campanha
GET  /campaigns/{id}                Detalhe
POST /campaigns/{id}/template       Atualizar template
POST /campaigns/{id}/extra-templates Variações anti-ban
POST /campaigns/{id}/settings       Configurações operacionais
POST /campaigns/{id}/start          Iniciar
POST /campaigns/{id}/pause          Pausar
POST /campaigns/{id}/resume         Retomar
POST /campaigns/{id}/cancel         Cancelar
POST /campaigns/{id}/delete         Excluir
GET  /campaigns/{id}/stats          JSON: contadores
GET  /campaigns/{id}/contacts       Lista contatos (paginado)
POST /campaigns/{id}/contacts/upload CSV
POST /campaigns/{id}/contacts/manual Adicionar manual
GET  /campaigns/{id}/failures/export CSV de falhas
GET  /whatsapp                      Página de sessão WA
GET  /whatsapp/qr                   JSON: QR code
POST /whatsapp/connect              Iniciar sessão
POST /whatsapp/restart              Reiniciar
POST /whatsapp/reset                Reset completo
GET  /settings/users                Gerenciar usuários
POST /settings/users                Criar usuário
POST /settings/users/{id}/toggle   Ativar/desativar
POST /settings/users/{id}/reset-pw Reset senha
GET  /settings/webhooks             Gerenciar webhooks
POST /settings/webhooks             Criar webhook
DELETE /settings/webhooks/{id}      Excluir webhook
POST /auth/change-password          Trocar senha
```

### SuperAdmin (`/admin/*` — usa `DATABASE_URL_ADMIN`)
```
GET  /admin                         Dashboard global (stats de todas orgs)
GET  /admin/stats                   JSON: métricas globais
GET  /admin/organizations           Lista orgs
POST /admin/organizations           Criar org + owner
POST /admin/organizations/{id}/suspend  Suspender
DELETE /admin/organizations/{id}    Excluir
GET  /admin/sessions                Estado de todas sessões WA
GET  /admin/audit-logs              Ações administrativas
```

---

## 15. Fases de Implementação (8 fases)

### Fase 1 — Fundação: PostgreSQL + Alembic + RLS + Redis
**Arquivos:** `database.py`, `models/`, `migrations/`, `docker-compose.yml`, `config.py`, `requirements.txt`

- Serviços postgres e redis no compose
- `config.py` com pydantic-settings
- `database.py`: engine único psycopg2 + `get_db`, `get_tenant_db`, `get_system_db`
- Modelos com todos os campos novos (next_batch_at, rq_job_id, etc.)
- Alembic: `001_initial_schema.py` (schema + roles + RLS policies + índices)
- Alembic: `002_seed_data.py` (org default + owner + sessão WA)
- **Verificação:** `alembic upgrade head` sem erros → RLS ativo → query sem `SET LOCAL` retorna vazio

### Fase 2 — Auth JWT + RBAC + Middleware RLS
**Arquivos:** `core/`, `routers/auth.py`, `templates/login.html`, `templates/change_password.html`

- JWT encode/decode + bcrypt
- `TenantContextMiddleware`, `get_current_user`, `require_roles`, `require_superadmin`
- Rotas: `/auth/login`, `/auth/logout`, `/auth/refresh`, `/auth/change-password`
- Redirect obrigatório para `must_change_password`
- **Verificação:** login → cookies JWT → rota protegida acessível → cross-tenant bloqueado pelo RLS

### Fase 3 — Fila Redis + Worker + Jobs Idempotentes
**Arquivos:** `queue/`, `workers/`, `services/campaign_orchestrator.py`

- Filas: high, default, low, webhooks
- `send_message_job` com guard de idempotência, limit check de sessão, delay inline
- `deliver_webhook_job` com retry RQ
- Orchestrator com `next_batch_at` e `SELECT FOR UPDATE SKIP LOCKED`
- Startup recovery no lifespan
- **Verificação:** job duplicado → RQ ignora → pausa devolve contatos para pending → jobs executam guard

### Fase 4 — Bridge Multi-Sessão + Session Sync
**Arquivos:** `wa-bridge/lib/session-manager.js`, `wa-bridge/server.js`, `services/whatsapp_client.py`, `services/session_sync.py`

- SessionManager no bridge com lazy init e `MAX_SESSIONS=10`
- Endpoints `/sessions/:key/*`
- `WhatsAppClient` por session_key
- `session_sync.run_forever()` em thread: poll bridge + warmup + stale recovery
- **Verificação:** 2 sessões → QR independentes → sync atualiza DB → desconexão pausa campanhas

### Fase 5 — Campanhas e Contatos Multi-Tenant
**Arquivos:** `routers/campaigns.py`, `routers/contacts.py`, `repositories/`, `services/campaign_service.py`, `services/limits_service.py`

- Pause/resume/cancel com garantia de devolução de contatos
- Todos os endpoints filtrados por org_id via `get_tenant_db`
- Limits service (plano)
- extra_templates JSONB
- **Verificação:** Org A não vê campanhas de Org B — testado direto no banco sem bypass

### Fase 6 — Gestão de Usuários, SuperAdmin e Anti-Ban
**Arquivos:** `routers/users.py`, `routers/admin.py`, `services/`, `utils/warmup.py`

- CRUD de usuários da org (owner/admin)
- Rotas `/admin/*` com `DATABASE_URL_ADMIN`
- Anti-ban: warmup + session limit + detecção de erros consecutivos
- **Verificação:** owner cria operator → operator sem /settings/users → superadmin vê cross-tenant

### Fase 7 — Dashboards e Webhooks
**Arquivos:** `routers/dashboard.py`, `routers/webhooks.py`, `templates/`

- Dashboard da org: stats + atividade recente + status WA
- Dashboard global: métricas + orgs + sessões
- Webhooks: CRUD + entrega via fila
- **Verificação:** webhook com HMAC válido → dashboard atualiza em tempo real

### Fase 8 — UX/UI e Testes Críticos
**Arquivos:** `templates/base.html`, `static/styles.css`, `tests/`

- Layout sidebar responsivo
- Progress bars de campanha
- Badges de status WA
- Testes críticos: RLS, idempotência, pausa/cancel com jobs enfileirados
- **Verificação:** testes críticos passam → sidebar mobile → progress bar real

---

## 16. Migração dos Dados Existentes

```python
# migrations/versions/002_seed_data.py

def upgrade():
    # 1. Org default
    op.execute("INSERT INTO organizations (name, slug, status, plan) VALUES ('Minha Empresa', 'minha-empresa', 'active', 'pro')")

    # 2. Owner (a partir da senha atual no .env)
    op.execute(f"""
        INSERT INTO users (organization_id, name, email, password_hash, role, is_superadmin)
        VALUES (1, 'Admin', '{ADMIN_EMAIL}', '{hash_password(ADMIN_PASSWORD)}', 'owner', true)
    """)

    # 3. Sessão WA (não conectada — novo QR obrigatório ou renomear diretório)
    op.execute("""
        INSERT INTO whatsapp_sessions (organization_id, session_key, status, warmup_daily_limit)
        VALUES (1, 'org-1', 'not_connected', 50)
    """)

    # 4. Dados existentes → org default
    op.execute("UPDATE campaigns SET organization_id = 1, created_by_user_id = 1")
    op.execute("UPDATE contacts  SET organization_id = 1")

    # 5. send_logs → campaign_logs
    op.execute("""
        INSERT INTO campaign_logs
            (campaign_id, organization_id, contact_id, event_type, message, meta_json, created_at)
        SELECT campaign_id, 1, contact_id, event_type, payload_excerpt,
               jsonb_build_object('http_status', http_status, 'error_class', error_class),
               created_at
        FROM send_logs
    """)
```

**Sessão WA:** renomear `.wwebjs_auth/session-mass-sender/` → `.wwebjs_auth/session-org-1/`
antes do primeiro deploy, ou simplesmente escanear novo QR (operação de 1 minuto).

---

## 17. Restore Operacional

### Checklist de restore após falha ou migração

```
☐ 1. PostgreSQL restaurado
     gunzip < backup.sql.gz | docker exec -i postgres psql -U mass_sender mass_sender
     docker compose exec app alembic current  # deve mostrar head

☐ 2. Subir serviços
     docker compose up -d
     # Startup recovery roda automaticamente e resolve stale contacts

☐ 3. Verificar logs de recovery
     docker compose logs app | grep startup_recovery

☐ 4. Sessões WhatsApp
     # Se volume wa_sessions intacto → sessions reconectam automaticamente
     # Se volume perdido → usuários de cada org precisam escanear novo QR

☐ 5. Fila Redis
     # Se volume redis_data intacto → jobs pendentes são retomados
     # Se volume perdido → stale contacts resolvidos pelo recovery → orchestrator reenfileira

☐ 6. Verificar campanhas running antes de liberar
     docker compose exec app python -c "
     from database import SessionLocal
     from models.campaign import Campaign
     with SessionLocal() as db:
         cs = db.query(Campaign).filter_by(status='running').all()
         print(f'{len(cs)} campanhas running')
     "
```

### Backup diário (cron no VPS)

```bash
# /etc/cron.d/mass-sender-backup
0 3 * * * root docker exec mass-sender-saas-postgres-1 pg_dump \
  -U mass_sender mass_sender | gzip > /backups/pg_$(date +\%Y\%m\%d).sql.gz
find /backups -name "pg_*.sql.gz" -mtime +30 -delete
```

---

## 18. Verificação por Fase

| Fase | Critério de Conclusão |
|---|---|
| 1 | PG + Redis up → RLS ativo → query sem SET LOCAL retorna vazio para app_user |
| 2 | Login → cookies JWT → middleware seta org_id → 403 para cross-tenant |
| 3 | Job duplicado ignorado → pausa devolve contatos para pending → jobs executam guard de status |
| 4 | 2 sessões independentes → desconexão pausa campanahstomáticas → recovery limpa stale contacts |
| 5 | Org A não lê dados de Org B no banco direto → limites de plano rejeitados |
| 6 | Warmup limita sessão → erros consecutivos pausam sessão 30min → superadmin vê cross-tenant |
| 7 | Webhook entregue com HMAC → dashboard polling correto → fila visível no admin |
| 8 | Testes críticos passam: RLS, idempotência, pausa-cancel → sidebar mobile funciona |

---

## 19. RAM e Escala

| Sessões WA ativas | RAM VPS recomendada |
|---|---|
| 1 | 2 GB |
| 3-5 | 4 GB |
| 6-10 | 8 GB |

**1 worker RQ** é suficiente para 10 orgs simultâneas (limitante real é o delay anti-ban, ~5-10s/msg).
Para crescer: adicionar instâncias `worker` no compose — stateless, sem configuração adicional.
