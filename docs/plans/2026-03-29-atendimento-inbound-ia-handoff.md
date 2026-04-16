# Atendimento Inbound com IA e Handoff Humano Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Adicionar atendimento inbound no número já conectado ao WhatsApp, com resposta automática por IA, persistência de conversas, idempotência por mensagem recebida e handoff obrigatório para um número humano configurado.

**Architecture:** O `wa-bridge` continuará como ponto de contato com o WhatsApp e passará a capturar mensagens inbound para enviá-las ao backend via webhook autenticado. O backend FastAPI será o orquestrador do fluxo: aplicará idempotência, persistirá conversa e mensagens, processará cada telefone de forma sequencial, chamará a IA via OpenRouter, decidirá entre resposta e handoff e enviará as mensagens usando o `WhatsAppClient` já existente. Oracle ficará explicitamente fora da v1, mas o desenho deixará um adapter isolado para futura integração sem refazer o fluxo.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, `httpx`, `whatsapp-web.js`, OpenRouter HTTP API.

---

### Task 1: Modelagem de conversa e idempotência

**Files:**
- Modify: `models.py`
- Modify: `main.py`
- Test: `tests/test_inbound_models.py`

**Step 1: Escrever testes de modelagem e idempotência**

Criar testes cobrindo:

- criação de `Conversation` com `customer_phone` único
- criação de `ConversationMessage` com `wa_message_id` único
- criação de `HandoffEvent`
- falha ao inserir dois registros com o mesmo `wa_message_id`

**Step 2: Executar o teste novo para validar falha inicial**

Run:
```bash
pytest tests/test_inbound_models.py -v
```

Expected:
- Falha porque os models e tabelas novas ainda não existem.

**Step 3: Implementar os models novos**

Adicionar em `models.py`:

- `Conversation`
  - `id`
  - `customer_phone`
  - `status`
  - `last_message_at`
  - `ai_consecutive_replies`
  - `handoff_target_phone`
  - `created_at`
  - `updated_at`
- `ConversationMessage`
  - `id`
  - `conversation_id`
  - `wa_message_id`
  - `direction`
  - `sender_type`
  - `message_text`
  - `raw_payload_excerpt`
  - `created_at`
- `HandoffEvent`
  - `id`
  - `conversation_id`
  - `reason`
  - `notified_phone`
  - `status`
  - `created_at`

Regras:

- `Conversation.customer_phone` deve ter índice único
- `ConversationMessage.wa_message_id` deve ter índice único global
- `Conversation.status` aceita `ai_active`, `waiting_human`, `closed`
- `ConversationMessage.direction` aceita `inbound`, `outbound`
- `ConversationMessage.sender_type` aceita `customer`, `ai`, `human_system`

**Step 4: Adicionar bootstrap de schema**

Em `main.py`:

- criar função `ensure_inbound_columns_and_indexes`
- chamá-la no `startup_event` depois de `Base.metadata.create_all(bind=engine)`
- seguir o mesmo estilo defensivo já usado em `ensure_campaign_operational_columns`

**Step 5: Rodar os testes novamente**

Run:
```bash
pytest tests/test_inbound_models.py -v
```

Expected:
- Todos os testes do arquivo passando.

**Step 6: Commit**

```bash
git add models.py main.py tests/test_inbound_models.py docs/plans/2026-03-29-atendimento-inbound-ia-handoff.md
git commit -m "feat: add inbound conversation models"
```

### Task 2: Serviço de domínio para conversas inbound

**Files:**
- Create: `services/conversation_service.py`
- Test: `tests/test_conversation_service.py`

**Step 1: Escrever testes do serviço**

Cobrir:

- buscar ou criar conversa por telefone normalizado
- deduplicar mensagem por `wa_message_id`
- salvar mensagem inbound
- não responder automaticamente se a conversa estiver `waiting_human`
- não responder automaticamente se a conversa estiver `closed`

**Step 2: Executar o teste para validar falha inicial**

Run:
```bash
pytest tests/test_conversation_service.py -v
```

Expected:
- Falha porque o serviço ainda não existe.

**Step 3: Implementar serviço**

Criar `services/conversation_service.py` com funções principais:

- `normalize_inbound_phone(raw_phone: str) -> str`
- `get_or_create_conversation(db, customer_phone: str) -> Conversation`
- `save_inbound_message(db, *, wa_message_id, from_phone, text, raw_payload_excerpt, push_name=None) -> tuple[Conversation, bool]`
- `append_outbound_message(db, *, conversation_id, text, sender_type) -> ConversationMessage`
- `mark_waiting_human(db, conversation_id, reason, notified_phone) -> None`
- `reopen_ai(db, conversation_id) -> None`
- `close_conversation(db, conversation_id) -> None`

Regras:

- a função de entrada deve retornar `duplicate=True` se `wa_message_id` já existir
- `Conversation.last_message_at` deve ser atualizada a cada inbound salvo
- conversa nova nasce em `ai_active`

**Step 4: Rodar os testes novamente**

Run:
```bash
pytest tests/test_conversation_service.py -v
```

Expected:
- Todos os testes do arquivo passando.

**Step 5: Commit**

```bash
git add services/conversation_service.py tests/test_conversation_service.py
git commit -m "feat: add inbound conversation service"
```

### Task 3: Contrato do webhook inbound no backend

**Files:**
- Modify: `main.py`
- Test: `tests/test_inbound_webhook_route.py`

**Step 1: Escrever testes da rota**

Cobrir:

- rejeita request sem token correto
- aceita payload válido
- retorna `duplicate=true` quando a mesma mensagem chega de novo
- salva mensagem e conversa
- retorna rápido sem depender do processamento completo da IA

**Step 2: Executar o teste para validar falha inicial**

Run:
```bash
pytest tests/test_inbound_webhook_route.py -v
```

Expected:
- Falha porque a rota ainda não existe.

**Step 3: Implementar a rota**

Adicionar em `main.py`:

- `POST /webhooks/whatsapp/inbound`

Contratos:

- autenticação por token dedicado em header, por exemplo `x-inbound-token`
- payload mínimo:
  - `wa_message_id`
  - `from_phone`
  - `to_phone`
  - `text`
  - `timestamp`
  - `push_name`
  - `message_type`
  - `from_me`
  - `raw_excerpt`

Resposta:

- `200 {"ok": true, "accepted": true, "duplicate": false}`
- `200 {"ok": true, "accepted": true, "duplicate": true}`

Comportamento:

- ignorar `from_me=true`
- validar que existe `wa_message_id`, `from_phone` e `text`
- usar `conversation_service.save_inbound_message`
- disparar processamento assíncrono sem bloquear a resposta

**Step 4: Rodar os testes novamente**

Run:
```bash
pytest tests/test_inbound_webhook_route.py -v
```

Expected:
- Todos os testes do arquivo passando.

**Step 5: Commit**

```bash
git add main.py tests/test_inbound_webhook_route.py
git commit -m "feat: add inbound webhook route"
```

### Task 4: Captura inbound no wa-bridge

**Files:**
- Modify: `wa-bridge/server.js`
- Test: `wa-bridge/tests/inbound-webhook.test.js`

**Step 1: Escrever testes do bridge**

Cobrir:

- evento inbound elegível dispara webhook para backend
- mensagem `fromMe` não dispara webhook
- mensagem de grupo não dispara webhook
- mensagem sem texto não dispara webhook
- falha de webhook não derruba o processo

**Step 2: Executar o teste para validar falha inicial**

Run:
```bash
node --test wa-bridge/tests/inbound-webhook.test.js
```

Expected:
- Falha porque o comportamento ainda não existe.

**Step 3: Implementar publicação de inbound**

Em `wa-bridge/server.js`:

- adicionar envs:
  - `BACKEND_INBOUND_WEBHOOK_URL`
  - `BACKEND_INBOUND_WEBHOOK_TOKEN`
- registrar listener de inbound do cliente WhatsApp
- filtrar mensagens não elegíveis
- montar payload normalizado
- enviar `fetch` autenticado ao backend
- registrar logs de sucesso e falha no `track`

Regras:

- nunca decidir handoff no bridge
- nunca chamar IA no bridge
- o bridge só captura e entrega

**Step 4: Rodar os testes novamente**

Run:
```bash
node --test wa-bridge/tests/inbound-webhook.test.js
```

Expected:
- Todos os testes do arquivo passando.

**Step 5: Commit**

```bash
git add wa-bridge/server.js wa-bridge/tests/inbound-webhook.test.js
git commit -m "feat: publish inbound whatsapp messages to backend"
```

### Task 5: Cliente OpenRouter e contrato do agente

**Files:**
- Create: `services/openrouter_client.py`
- Create: `services/ai_agent.py`
- Test: `tests/test_ai_agent.py`

**Step 1: Escrever testes do agente**

Cobrir:

- retorna `reply` com texto válido quando a IA responde normalmente
- retorna `handoff` quando a IA sinaliza intenção de compra, pedido, desconto ou baixa confiança
- retorna `handoff` quando a IA falha
- retorna `handoff` quando a resposta vier inválida

**Step 2: Executar o teste para validar falha inicial**

Run:
```bash
pytest tests/test_ai_agent.py -v
```

Expected:
- Falha porque os serviços ainda não existem.

**Step 3: Implementar cliente e agente**

Criar `services/openrouter_client.py`:

- leitura de `OPENROUTER_API_KEY`
- leitura de `OPENROUTER_MODEL`
- `OPENROUTER_BASE_URL` opcional
- timeout explícito
- método `complete_json(...)`

Criar `services/ai_agent.py`:

- método principal `decide_next_action(...)`
- saída estruturada:
  - `action`
  - `reply_text`
  - `handoff_reason`
  - `confidence`

Regras fixas:

- tom humano e comercial
- frases curtas
- não inventar dados
- não negociar
- não concluir pedido
- handoff obrigatório para:
  - intenção de compra
  - pedido
  - desconto
  - baixa confiança

Fallback:

- qualquer falha do provider deve virar `handoff`

**Step 4: Rodar os testes novamente**

Run:
```bash
pytest tests/test_ai_agent.py -v
```

Expected:
- Todos os testes do arquivo passando.

**Step 5: Commit**

```bash
git add services/openrouter_client.py services/ai_agent.py tests/test_ai_agent.py
git commit -m "feat: add openrouter ai decision layer"
```

### Task 6: Serviço de handoff humano

**Files:**
- Create: `services/handoff_service.py`
- Test: `tests/test_handoff_service.py`

**Step 1: Escrever testes do handoff**

Cobrir:

- envia mensagem padrão ao cliente
- envia resumo ao número humano global
- registra `HandoffEvent`
- coloca conversa em `waiting_human`
- falha explícita se `HUMAN_HANDOFF_PHONE` estiver ausente

**Step 2: Executar o teste para validar falha inicial**

Run:
```bash
pytest tests/test_handoff_service.py -v
```

Expected:
- Falha porque o serviço ainda não existe.

**Step 3: Implementar serviço**

Criar `services/handoff_service.py` com função principal:

- `perform_handoff(db, conversation_id: int, reason: str, client: WhatsAppClient) -> None`

Regras:

- mensagem ao cliente deve ser exatamente:
  - `Vou passar seu atendimento para meu gerente.`
- o humano deve receber:
  - telefone do cliente
  - últimas mensagens
  - motivo do handoff
- o número do humano vem de `HUMAN_HANDOFF_PHONE`

**Step 4: Rodar os testes novamente**

Run:
```bash
pytest tests/test_handoff_service.py -v
```

Expected:
- Todos os testes do arquivo passando.

**Step 5: Commit**

```bash
git add services/handoff_service.py tests/test_handoff_service.py
git commit -m "feat: add human handoff service"
```

### Task 7: Engine inbound com lock por conversa

**Files:**
- Create: `services/inbound_engine.py`
- Modify: `main.py`
- Test: `tests/test_inbound_engine.py`

**Step 1: Escrever testes do engine**

Cobrir:

- processa uma conversa em `ai_active`
- não processa quando status é `waiting_human`
- não processa quando status é `closed`
- limita a 5 respostas consecutivas e faz handoff
- garante execução sequencial por `conversation_id`
- agrega mensagens curtas consecutivas antes da IA

**Step 2: Executar o teste para validar falha inicial**

Run:
```bash
pytest tests/test_inbound_engine.py -v
```

Expected:
- Falha porque o engine ainda não existe.

**Step 3: Implementar engine**

Criar `services/inbound_engine.py` com:

- lock em memória por `conversation_id`
- fila lógica disparada pela rota inbound
- uso de `conversation_service`, `ai_agent`, `handoff_service` e `WhatsAppClient`

Pseudo-fluxo:

```text
webhook -> salva inbound -> agenda processamento
processamento -> lock conversa
processamento -> lê estado da conversa
processamento -> agrega mensagens inbound abertas
processamento -> chama IA
IA=reply -> delay 1-3s -> envia resposta -> salva outbound -> incrementa contador
IA=handoff -> executa handoff -> status waiting_human
erro IA -> handoff
unlock
```

Regras:

- máximo de 5 respostas consecutivas por conversa
- após 5, handoff obrigatório
- se a conversa voltar para `ai_active`, o contador pode ser resetado

**Step 4: Integrar no startup**

Em `main.py`:

- criar instância global do `InboundEngine`
- iniciar qualquer task necessária no `startup_event`
- encerrar com segurança no `shutdown_event`

**Step 5: Rodar os testes novamente**

Run:
```bash
pytest tests/test_inbound_engine.py -v
```

Expected:
- Todos os testes do arquivo passando.

**Step 6: Commit**

```bash
git add services/inbound_engine.py main.py tests/test_inbound_engine.py
git commit -m "feat: add inbound conversation engine"
```

### Task 8: Rotas operacionais de conversa e observabilidade mínima

**Files:**
- Modify: `main.py`
- Modify: `templates/index.html`
- Modify: `templates/campaign.html`
- Modify: `static/app.js`
- Test: `tests/test_conversation_routes.py`

**Step 1: Escrever testes das rotas operacionais**

Cobrir:

- listar conversas
- detalhar conversa
- handoff manual
- fechar conversa
- reabrir conversa para IA
- exigir autenticação admin

**Step 2: Executar o teste para validar falha inicial**

Run:
```bash
pytest tests/test_conversation_routes.py -v
```

Expected:
- Falha porque as rotas ainda não existem.

**Step 3: Implementar rotas**

Adicionar em `main.py`:

- `GET /conversations`
- `GET /conversations/{id}`
- `POST /conversations/{id}/handoff`
- `POST /conversations/{id}/close`
- `POST /conversations/{id}/reopen-ai`

Comportamento:

- rotas protegidas por `require_auth`
- payloads simples em JSON
- respostas consistentes com o padrão do projeto

**Step 4: Adicionar UI mínima**

Adicionar no painel:

- lista simples de conversas recentes
- status visível
- botão de handoff manual
- botão de fechar conversa
- botão de reabrir para IA

Sem escopo nesta fase:

- chat realtime completo
- operador respondendo pelo painel
- websocket

**Step 5: Rodar os testes novamente**

Run:
```bash
pytest tests/test_conversation_routes.py -v
```

Expected:
- Todos os testes do arquivo passando.

**Step 6: Commit**

```bash
git add main.py templates/index.html templates/campaign.html static/app.js tests/test_conversation_routes.py
git commit -m "feat: add inbound conversation admin routes"
```

### Task 9: Variáveis de ambiente e documentação operacional

**Files:**
- Modify: `.env.example`
- Modify: `docs/LOCAL_ENVIRONMENT.md`
- Modify: `docs/OPERATIONS.md`
- Test: `tests/test_env_loading.py`

**Step 1: Estender testes de env**

Cobrir leitura das novas variáveis:

- `BACKEND_INBOUND_WEBHOOK_URL`
- `BACKEND_INBOUND_WEBHOOK_TOKEN`
- `OPENROUTER_API_KEY`
- `OPENROUTER_MODEL`
- `OPENROUTER_BASE_URL`
- `HUMAN_HANDOFF_PHONE`

**Step 2: Executar o teste**

Run:
```bash
pytest tests/test_env_loading.py -v
```

Expected:
- Pode falhar até a documentação e defaults serem atualizados.

**Step 3: Atualizar env example e docs**

Documentar:

- como ativar webhook inbound no bridge
- como configurar OpenRouter
- como configurar o número humano
- limitações atuais da v1

**Step 4: Rodar o teste novamente**

Run:
```bash
pytest tests/test_env_loading.py -v
```

Expected:
- Testes relevantes passando.

**Step 5: Commit**

```bash
git add .env.example docs/LOCAL_ENVIRONMENT.md docs/OPERATIONS.md tests/test_env_loading.py
git commit -m "docs: add inbound ai environment setup"
```

### Task 10: Validação integrada e não-regressão

**Files:**
- Modify: `tests/test_whatsapp_client.py`
- Modify: `tests/test_bridge_routes.py`
- Modify: `tests/test_send_engine.py`
- Create: `tests/test_inbound_end_to_end.py`

**Step 1: Adicionar cenários integrados**

Cobrir:

- inbound -> webhook -> IA responde
- inbound -> IA decide handoff
- inbound duplicado -> sem resposta duplicada
- falha OpenRouter -> handoff
- regressão: envio outbound antigo continua funcionando

**Step 2: Rodar suíte focada**

Run:
```bash
pytest tests/test_inbound_end_to_end.py tests/test_whatsapp_client.py tests/test_bridge_routes.py tests/test_send_engine.py -v
```

Expected:
- Todos os testes relevantes passando.

**Step 3: Rodar suíte completa**

Run:
```bash
pytest tests/ -v
```

Expected:
- Nenhuma regressão nos fluxos atuais.

**Step 4: Commit final**

```bash
git add tests/test_inbound_end_to_end.py tests/test_whatsapp_client.py tests/test_bridge_routes.py tests/test_send_engine.py
git commit -m "test: validate inbound ai flow without breaking outbound campaigns"
```

## Decisões fechadas nesta versão

- Escopo inbound da v1: todo inbound recebido no número conectado.
- Provider de IA da v1: OpenRouter.
- Oracle: fora da v1.
- Handoff: avisar o cliente e notificar um número humano global por ambiente.
- Persistência: continuar com SQLite nesta fase.
- Concorrência: lock em memória por `conversation_id`, assumindo instância única.
- Mensagem padrão de handoff ao cliente:

```text
Vou passar seu atendimento para meu gerente.
```

## Critérios de aceite

- Cada `wa_message_id` inbound é processado no máximo uma vez.
- Conversas `waiting_human` e `closed` não recebem novas respostas da IA.
- A IA responde de forma curta e comercial quando permitido.
- Após 5 respostas consecutivas da IA, o sistema faz handoff.
- Intenção de compra, pedido, desconto ou baixa confiança causam handoff.
- O humano recebe resumo da conversa no número configurado.
- O fluxo outbound atual de campanhas continua funcionando sem regressão.
