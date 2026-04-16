# Guia do Ambiente de Testes (Docker Local)

Este documento descreve como gerenciar o ambiente de desenvolvimento e testes isolado utilizando Docker. Este ambiente replica a infraestrutura da VPS em sua máquina local para validação de funcionalidades.

Este guia cobre apenas o modo Docker.
Se você quiser rodar a aplicação localmente fora de containers com `uvicorn` e `npm start`, use [OPERATIONS.md](/Users/diego/Desktop/IA/mass-sender-saas-vps/docs/OPERATIONS.md).

Mesmo neste modo Docker, os testes backend executados no host com `.venv` agora assumem Python 3.11, em linha com o `Dockerfile`.

> **IMPORTANTE:** Execute os comandos a partir da raiz do repositório que contém o `docker-compose.yml`.
> O worktree `.worktrees/local-testing` só deve ser usado se ele realmente existir na sua máquina.

---

## 1. Comandos de Inicialização

### Modo deste documento
Neste arquivo, sempre que falarmos em "subir o ambiente", estamos falando de:

- `app` em container Docker
- `wa-bridge` em container Docker
- volumes Docker para banco local e sessão WhatsApp

Nao use este guia para misturar `docker compose` com `uvicorn`/`npm start` no host.
Se a intenção for debug local sem Docker, siga o outro documento.

### Pré-requisito para testes no host
Se você quiser rodar `pytest` localmente fora do container, use:

- Python 3.11
- virtualenv em `.venv`

Comandos recomendados:
```bash
/opt/homebrew/bin/python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Iniciar Tudo (Background)
Sobe os containers da aplicação FastAPI e do motor do WhatsApp (wa-bridge) de uma só vez.
```bash
docker compose up -d
```

### Reconstruir Imagens
Use este comando se houver mudanças no código-fonte, `Dockerfile` ou `requirements.txt`.
```bash
docker compose build
```

---

## 2. Controle Individual de Serviços

Você pode parar ou iniciar apenas um dos componentes para realizar testes de resiliência.

### Parar o Motor do WhatsApp (wa-bridge)
Útil para testar como a aplicação reage à perda de conexão com o WhatsApp.
```bash
docker compose stop wa-bridge
```

### Parar a Aplicação (app)
```bash
docker compose stop app
```

### Reiniciar um serviço específico
```bash
docker compose restart <nome-do-serviço>
```

---

## 3. Monitoramento e Diagnóstico

### Ver Logs em Tempo Real
Acompanhe o que está acontecendo nos dois serviços simultaneamente.
```bash
docker compose logs -f
```

### Consultar Logs de apenas um serviço
```bash
docker compose logs -f wa-bridge
```

### Verificar Status dos Containers
Confirme se os containers estão "Up" e quais portas estão mapeadas.
```bash
docker compose ps
```

---

## 4. Acesso ao Ambiente

Após iniciar os serviços com sucesso, utilize as URLs abaixo:

| Serviço | URL Local | Descrição |
| :--- | :--- | :--- |
| **Dashboard App** | [http://localhost:8000](http://localhost:8000) | Interface principal de gestão. |
| **API do Bridge** | [http://localhost:3010/health](http://localhost:3010/health) | Saúde técnica do motor WhatsApp. |

**Credenciais Padrão (Ambiente Local):**
*   **Senha do Administrador:** `admin123` (Conforme configurado em `.env`)

## 4.1 Configuração do Inbound com IA

Para ativar o atendimento inbound com IA na v1, configure no `.env`:

```env
INBOUND_WEBHOOK_TOKEN=troque-este-token
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=openai/gpt-4.1-mini
HUMAN_HANDOFF_PHONE=+5581888888888
```

E no ambiente do `wa-bridge`:

```env
BACKEND_INBOUND_WEBHOOK_URL=http://app:8000/webhooks/whatsapp/inbound
BACKEND_INBOUND_WEBHOOK_TOKEN=troque-este-token
```

Observações:
- o número conectado no `wa-bridge` passa a receber e encaminhar mensagens inbound
- a IA responde apenas enquanto a conversa estiver em `ai_active`
- após handoff, a conversa entra em `waiting_human` e a IA para de responder
- o `wa-bridge` agora também lê `wa-bridge/.env` e `../.env`, então o `.env` da raiz já pode ser usado no ambiente local
- no modo Docker, essas variáveis precisam estar disponíveis para os containers via `.env` e `docker compose`

---

## 5. Execução de Testes Automatizados

Para rodar a suíte de testes completa **dentro do container** (garantindo que o ambiente isolado está saudável):

```bash
docker compose exec app pytest tests/
```

---

## 6. Limpeza Total (Reset)

Para remover todos os containers e apagar os volumes de dados (banco de dados e sessões do WhatsApp locais):
```bash
docker compose down -v
```
*> Cuidado: Isso apagará qualquer campanha de teste ou sessão de WhatsApp configurada localmente.*
