# Plano de Implementação: Ambiente de Teste Local via Docker

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Objetivo:** Configurar e validar o ambiente de desenvolvimento e teste local utilizando Docker para garantir paridade com a produção (VPS).

**Arquitetura:** Orquestração via `docker-compose.yml` dos serviços `app` (FastAPI) e `wa-bridge` (Node.js) com volumes persistentes para SQLite e sessões do WhatsApp.

**Stack Tecnológica:** Docker, Docker Compose, FastAPI (Python), Node.js, SQLite.

---

### Task 1: Preparação do Ambiente e Imagens

**Arquivos:**
- Modificar: `.env`
- Executar: `docker compose build`

**Passo 1: Validar `.env` para contexto Docker**
Garantir que as variáveis de ambiente estão compatíveis com os nomes dos serviços no Docker.
No arquivo `.env`, o `WA_BRIDGE_BASE_URL` será sobrescrito pelo `docker-compose.yml`, mas manteremos uma versão local se necessário.

**Passo 2: Construir as imagens**
Executar o comando de build para garantir que todas as dependências estão atualizadas.
Run: `docker compose build`
Expected: Sucesso no build das imagens `app` e `wa-bridge`.

**Passo 3: Commit inicial**
```bash
git add .env docker-compose.yml Dockerfile wa-bridge/Dockerfile
git commit -m "infra: preparando ambiente docker local"
```

---

### Task 2: Inicialização e Verificação de Conectividade

**Arquivos:**
- Executar: `docker compose up -d`
- Testar: `curl http://localhost:8000/health` (se existir) ou `curl http://localhost:3010/health`

**Passo 1: Subir os serviços**
Run: `docker compose up -d`
Expected: Containers `mass-sender-saas-vps-app-1` e `mass-sender-saas-vps-wa-bridge-1` rodando.

**Passo 2: Verificar logs do Bridge**
Run: `docker compose logs -f wa-bridge`
Expected: Bridge inicializado e aguardando conexão.

**Passo 3: Verificar conectividade da App com o Bridge**
Run: `docker compose exec app curl http://wa-bridge:3010/health`
Expected: `{"status": "online"}` ou similar.

---

### Task 3: Validação de Funcionalidade (CRUD e CSV)

**Arquivos:**
- Testar: Fluxo de upload de CSV via UI (manual ou via Playwright)

**Passo 1: Executar testes automatizados dentro do container**
Run: `docker compose exec app pytest tests/test_csv_parser.py`
Expected: Todos os testes de parser passando.

**Passo 2: Validar acesso UI**
Acessar `http://localhost:8000` no navegador.
Expected: Tela de login ou dashboard visível.

---

### Task 4: Teste de Envio (Mock/Dry Run)

**Arquivos:**
- Testar: Criação de campanha e simulação.

**Passo 1: Criar campanha de teste**
Usar a UI para carregar um CSV de teste e realizar o "Dry Run".
Expected: Resumo da campanha exibido corretamente com estimativas.
