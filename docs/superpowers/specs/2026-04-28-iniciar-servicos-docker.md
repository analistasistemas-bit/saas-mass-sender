# Especificação: Inicialização de Serviços via Docker Local

Este documento detalha o procedimento para subir o ambiente completo do Mass Sender SaaS utilizando Docker Compose, conforme as diretrizes do projeto e o documento `docs/LOCAL_ENVIRONMENT.md`.

## 1. Arquitetura do Ambiente

O ambiente é composto por dois serviços principais:

- **app**: Backend FastAPI (Python 3.11) que gerencia campanhas, contatos e lógica de negócio.
- **wa-bridge**: Bridge Node.js que mantém a sessão do WhatsApp Web e expõe a API de envio.

Ambos os serviços compartilham a rede interna do Docker e utilizam volumes persistentes para banco de dados e sessões de autenticação.

## 2. Requisitos de Configuração

- O arquivo `.env` deve estar presente na raiz do projeto.
- O Docker e o Docker Compose devem estar instalados e rodando no host.

## 3. Procedimento de Execução

### Passo 1: Build e Up
Será executado o comando para reconstruir as imagens (se necessário) e iniciar os containers em modo detach:
```bash
docker compose up -d --build
```

### Passo 2: Monitoramento de Logs
Imediatamente após subir, os logs devem ser monitorados para identificar a geração de QR Code ou erros de inicialização:
```bash
docker compose logs -f
```

### Passo 3: Verificação de Conectividade
Validação manual ou via script dos endpoints de saúde:
- **Backend**: `curl http://localhost:8000/health`
- **Bridge**: `curl http://localhost:3010/health`

## 4. Acesso ao Sistema
- **URL**: `http://localhost:8000/login`
- **Senha**: `admin123` (Padrão local)

## 5. Critérios de Sucesso
- Ambos os containers com status `Up`.
- Backend respondendo com `backend_reachable: true` no healthcheck.
- Bridge aguardando conexão ou em estado `ready`.
