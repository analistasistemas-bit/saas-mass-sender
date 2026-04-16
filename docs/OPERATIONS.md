# Operations Guide

## Objetivo

Este documento descreve como subir, parar, testar e manter o backend atual do projeto.
Ele cobre:

- backend Python/FastAPI
- `wa-bridge` em Node.js
- banco SQLite local
- stack legada com Evolution API via Docker
- comandos de diagnóstico e manutenção

Este documento é a referência para execução local fora do Docker.
Se a intenção for usar o ambiente isolado por containers com `docker compose up -d`, use [LOCAL_ENVIRONMENT.md](/Users/diego/Desktop/IA/mass-sender-saas-vps/docs/LOCAL_ENVIRONMENT.md).

Para o uso do aplicativo no dia a dia, consulte:

- [USER_GUIDE.md](/Users/mac/Desktop/IA/mass-sender/docs/USER_GUIDE.md)

## Visão Geral

O backend atual roda em dois processos principais:

1. `FastAPI`
Responsável por campanhas, contatos, validações, worker de envio, dry-run, test-run, start/pause/resume/cancel e exportação de falhas.

2. `wa-bridge`
Responsável por manter uma sessão local do WhatsApp Web e expor uma API mínima para o backend Python enviar mensagens.

Fluxo principal em produção local:

```text
Frontend futuro -> FastAPI -> wa-bridge -> WhatsApp Web
Inbound WhatsApp -> wa-bridge -> webhook FastAPI -> IA/handoff
```

## Modos de Execução

Existem dois modos suportados e eles nao devem ser misturados:

1. Docker local
- sobe `app` e `wa-bridge` em containers
- comando principal: `docker compose up -d`
- documentação: [LOCAL_ENVIRONMENT.md](/Users/diego/Desktop/IA/mass-sender-saas-vps/docs/LOCAL_ENVIRONMENT.md)

2. Local sem Docker
- sobe `FastAPI` com `uvicorn`
- sobe `wa-bridge` com `npm start`
- documentação: este arquivo

Quando este arquivo usar comandos como `uvicorn main:app --reload` e `npm start`, ele está descrevendo apenas o modo local sem Docker.

## Endpoints Principais

- `http://127.0.0.1:3010/health`
Funcao: healthcheck do `wa-bridge` (sessao WhatsApp Web).
Quando usar: confirmar se o bridge esta no ar e conectado.

- `http://127.0.0.1:3010/session`
Funcao: estado detalhado da sessao do bridge (`connected`, `state`, `lastError`, `history`).
Quando usar: diagnostico quando QR, conexao ou envio falham.

- `http://127.0.0.1:8000/health`
Funcao: healthcheck do backend FastAPI e do provider WhatsApp ativo.
Quando usar: validar se o backend leu `.env` e se o provider esta acessivel.

- `http://127.0.0.1:8000/login`
Funcao: entrada do console operacional do sistema.
Quando usar: acessar a interface para operar campanhas manualmente.

## Estrutura Relevante

- [main.py](/Users/mac/Desktop/IA/mass-sender/main.py): bootstrap FastAPI e rotas
- [database.py](/Users/mac/Desktop/IA/mass-sender/database.py): SQLite e sessão SQLAlchemy
- [services/send_engine.py](/Users/mac/Desktop/IA/mass-sender/services/send_engine.py): worker persistente
- [services/whatsapp.py](/Users/mac/Desktop/IA/mass-sender/services/whatsapp.py): cliente de provedor WhatsApp
- [wa-bridge/server.js](/Users/mac/Desktop/IA/mass-sender/wa-bridge/server.js): bridge local com WhatsApp Web
- [wa-bridge/fetch-qr.js](/Users/mac/Desktop/IA/mass-sender/wa-bridge/fetch-qr.js): exporta QR para PNG
- [.env](/Users/mac/Desktop/IA/mass-sender/.env): configuração local
- [docker-compose.evolution.yml](/Users/mac/Desktop/IA/mass-sender/docker-compose.evolution.yml): stack legada da Evolution

## Pré-Requisitos

### Python

- Python 3.11
- `venv` criado em `.venv`
- recomendacao: manter a mesma versao do `Dockerfile` para evitar divergencias entre host e container

### Node.js

- Node.js 20 LTS recomendado
- Node.js 22 LTS aceito
- Node.js 25+ nao suportado para o `wa-bridge`
- `npm` disponível

### Docker

Necessário apenas para a opção legada com Evolution API.

## Configuração de Ambiente

Arquivo principal:

- [.env](/Users/mac/Desktop/IA/mass-sender/.env)

Exemplo mínimo para o fluxo padrão com `wa-bridge`:

```env
APP_ADMIN_PASSWORD=admin123
DB_PATH=app.db
WHATSAPP_PROVIDER=bridge
WA_BRIDGE_BASE_URL=http://127.0.0.1:3010
WA_BRIDGE_API_KEY=
INBOUND_WEBHOOK_TOKEN=troque-este-token
OPENROUTER_API_KEY=
OPENROUTER_MODEL=openai/gpt-4.1-mini
HUMAN_HANDOFF_PHONE=+5581888888888
BACKEND_INBOUND_WEBHOOK_URL=http://127.0.0.1:8000/webhooks/whatsapp/inbound
BACKEND_INBOUND_WEBHOOK_TOKEN=troque-este-token
```

Observações:

- o backend agora carrega `.env` automaticamente
- variáveis exportadas no shell continuam tendo prioridade sobre `.env`
- `DB_PATH` controla o SQLite local
- `INBOUND_WEBHOOK_TOKEN` e `BACKEND_INBOUND_WEBHOOK_TOKEN` devem ter o mesmo valor
- `HUMAN_HANDOFF_PHONE` define o número global que recebe os handoffs humanos

## Atendimento Inbound com IA

Na v1, o atendimento inbound funciona assim:

- o `wa-bridge` captura mensagens recebidas no número conectado
- o bridge publica webhook para `POST /webhooks/whatsapp/inbound`
- o backend aplica idempotência por `wa_message_id`
- a IA responde enquanto a conversa estiver em `ai_active`
- quando houver intenção de compra, pedido, desconto, baixa confiança ou 5 respostas consecutivas, o sistema envia:
  - `Vou passar seu atendimento para meu gerente.`
  - resumo do caso para `HUMAN_HANDOFF_PHONE`

Estados da conversa:

- `ai_active`
- `waiting_human`
- `closed`

## Instalação Inicial

### Dependências Python

```bash
cd /Users/diego/Desktop/IA/mass-sender-saas-vps
/opt/homebrew/bin/python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Dependências do bridge

```bash
cd /Users/diego/Desktop/IA/mass-sender-saas-vps/wa-bridge
npm install
```

## Subida dos Serviços

### 1. Subir o `wa-bridge`

```bash
cd /Users/diego/Desktop/IA/mass-sender-saas-vps/wa-bridge
npm start
```

O que `npm start` faz:

- executa `node server.js`
- sobe um servidor HTTP local na porta `3010`
- inicializa o `whatsapp-web.js`
- gera QR quando necessário
- mantém a sessão do WhatsApp Web para o backend Python usar

O bridge precisa permanecer rodando para:

- o backend conseguir fazer `test-run`
- o worker conseguir enviar campanhas
- a sessão do WhatsApp permanecer ativa

Autorecuperação implementada:

- se o `wa-bridge` encontrar o erro `The browser is already running for ...session-mass-sender`
- ele tenta localizar e encerrar automaticamente apenas processos do `Google Chrome for Testing` presos no `userDataDir` da sessão atual
- depois disso, ele tenta inicializar novamente sem exigir intervenção manual

Se mesmo após a limpeza automática ainda houver `remaining` no log de `stale_browser_cleanup`, aí sim existe um travamento fora do fluxo esperado e vale intervenção manual.

### 2. Subir o backend FastAPI

```bash
cd /Users/diego/Desktop/IA/mass-sender-saas-vps
source .venv/bin/activate
uvicorn main:app --reload
```

### 3. Ordem recomendada

1. subir `wa-bridge`
2. conectar o WhatsApp
3. subir `FastAPI`
4. validar healthchecks
5. executar `test-run`
6. iniciar campanha real

## Como Conectar o WhatsApp

### Verificar estado da sessão

```bash
curl -s http://127.0.0.1:3010/health ; echo
curl -s http://127.0.0.1:3010/session ; echo
```

Estado esperado quando ainda não está conectado:

- `connected: false`
- `hasQr: true`
- `state: "qr_ready"`

### Exportar e abrir o QR

```bash
cd /Users/mac/Desktop/IA/mass-sender/wa-bridge
npm run fetch-qr
open /tmp/mass-sender-wa-qr.png
```

Depois escaneie o QR pelo WhatsApp no celular.

Estado esperado após conectar:

- `connected: true`
- `state: "ready"`

## Healthchecks

### Bridge

```bash
curl -s http://127.0.0.1:3010/health ; echo
```

### Backend FastAPI

```bash
curl -s http://127.0.0.1:8000/health ; echo
```

No fluxo padrão, o esperado no backend é:

- `provider: "bridge"`
- `backend_configured: true`
- `backend_reachable: true`

## Login e Sessão do App

### Login via terminal

```bash
curl -i -c /tmp/ms.cookie -X POST http://127.0.0.1:8000/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data "password=admin123"
```

### Ver cookie salvo

```bash
cat /tmp/ms.cookie
```

## Operação Pela Tela

Depois de subir `wa-bridge` e `FastAPI`, o fluxo normal pode ser feito em `http://127.0.0.1:8000/login`.

Fluxo de operador resumido:

1. conectar o WhatsApp na home
2. criar ou abrir uma campanha
3. ajustar a mensagem
4. enviar o CSV
5. simular
6. enviar teste
7. iniciar campanha
8. acompanhar progresso
9. exportar falhas quando necessário

O passo a passo completo está em:

- [USER_GUIDE.md](/Users/mac/Desktop/IA/mass-sender/docs/USER_GUIDE.md)

### Formato de CSV aceito no upload

O sistema aceita dois layouts de cabeçalho:

- padrão: `nome,telefone,email`
- legado: `NOME_CLIENTE,TELEFONE,E_MAIL`

A primeira coluna também pode ser um índice extra (por exemplo `1,2,3...`) antes do nome do cliente.

Exemplo legado válido:

```csv
,"NOME_CLIENTE","TELEFONE","E_MAIL"
1,"EMMET DOUGLAS DOS SANTOS FEIT","5581992049923",""
2,"RWC WERI CONFECCAO","5581984299667",""
```

### Simular campanha

- botão: `Simular campanha`
- função: mostrar uma previsão da campanha sem mandar mensagem real
- o resultado exibe:
  - quantos contatos estão prontos para envio
  - quantos são inválidos
  - tempo estimado
  - prévia legível das próximas mensagens

Se a campanha já tiver terminado ou não tiver fila pendente, a tela mostra uma mensagem amigável em vez de JSON cru.

### Enviar teste

- botão: `Enviar teste`
- função: enviar mensagem real para a amostra configurada
- requisito: existir pelo menos um contato `pending`

Se não houver contatos pendentes, a tela explica que é preciso usar `Reiniciar campanha`.

### Reiniciar campanha

- botão: `Reiniciar campanha`
- função: recriar a fila na mesma campanha, sem criar outra

Ao clicar, um modal oferece:

- `Reenviar só falhas`
- `Reenviar tudo`

Regras:

- `Reenviar só falhas` recoloca na fila apenas contatos `failed` e `processing`
- `Reenviar tudo` recoloca na fila contatos `sent`, `failed` e `processing`
- contatos `invalid` nunca voltam para a fila
- a campanha volta para status `ready`
- o histórico permanece salvo nos logs

## Operação Básica via Terminal

### Criar campanha

```bash
CID=$(
  curl -si -b /tmp/ms.cookie -X POST http://127.0.0.1:8000/campaigns \
    -H "Content-Type: application/x-www-form-urlencoded" \
    --data "name=Minha campanha" \
  | awk -F'/' '/^location: \/campaigns\// {gsub("\r","",$3); print $3}'
)
echo "$CID"
```

### Definir template

```bash
curl -i -b /tmp/ms.cookie -X POST \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "message_template=Oi, {{nome}}! Este é um teste." \
  "http://127.0.0.1:8000/campaigns/$CID/template"
```

### Upload de CSV

```bash
curl -i -b /tmp/ms.cookie -X POST \
  -F "csv_file=@/tmp/contatos_teste.csv;type=text/csv" \
  "http://127.0.0.1:8000/campaigns/$CID/contacts/upload"
```

### Simulação

```bash
curl -i -b /tmp/ms.cookie -X POST \
  "http://127.0.0.1:8000/campaigns/$CID/dry-run"
```

### Enviar teste

```bash
curl -i -b /tmp/ms.cookie -X POST -F "sample_size=1" \
  "http://127.0.0.1:8000/campaigns/$CID/test-run"
```

### Iniciar campanha

```bash
curl -i -b /tmp/ms.cookie -X POST \
  "http://127.0.0.1:8000/campaigns/$CID/start"
```

### Pausar campanha

```bash
curl -i -b /tmp/ms.cookie -X POST \
  "http://127.0.0.1:8000/campaigns/$CID/pause"
```

### Retomar campanha

```bash
curl -i -b /tmp/ms.cookie -X POST \
  "http://127.0.0.1:8000/campaigns/$CID/resume"
```

### Cancelar campanha

```bash
curl -i -b /tmp/ms.cookie -X POST \
  "http://127.0.0.1:8000/campaigns/$CID/cancel"
```

### Consultar estatísticas

```bash
curl -s -b /tmp/ms.cookie \
  "http://127.0.0.1:8000/campaigns/$CID/stats" ; echo
```

### Monitoramento contínuo

```bash
while true; do
  curl -s -b /tmp/ms.cookie "http://127.0.0.1:8000/campaigns/$CID/stats"
  echo
  sleep 3
done
```

## Operação 100% Pela Tela

Premissa: apenas subir os dois serviços no terminal.

1. Suba `wa-bridge` com `npm start`.
2. Suba FastAPI com `uvicorn main:app --reload`.
3. Abra `http://127.0.0.1:8000/login`.
4. Faça login com `APP_ADMIN_PASSWORD`.
5. Na home, use o bloco `Canal WhatsApp`:
   - `Gerar QR para conectar` para exibir QR
   - escaneie no celular
   - confirme o estado conectado no painel
6. Ainda na home, crie a campanha.
7. Na página da campanha:
   - salve a mensagem
   - faça upload do CSV
   - confira a seção `Contatos importados`
   - execute `Simular campanha`
   - execute `Enviar teste`
   - execute `Iniciar campanha`
8. Monitore progresso, narrativa e logs inteligentes na própria página.
9. Use `Pausar campanha`, `Retomar campanha`, `Cancelar campanha`, `Reiniciar campanha` e `Exportar falhas` pela UI.

## Banco de Dados

### Arquivo do banco

- [app.db](/Users/mac/Desktop/IA/mass-sender/app.db)

Arquivos auxiliares do SQLite:

- `app.db-wal`
- `app.db-shm`

### Consultar logs recentes

```bash
python3 - <<'PY'
import sqlite3
con = sqlite3.connect('app.db')
for row in con.execute("select id,campaign_id,contact_id,event_type,http_status,error_class,payload_excerpt,created_at from send_logs order by id desc limit 20"):
    print(row)
PY
```

### Consultar contatos

```bash
python3 - <<'PY'
import sqlite3
con = sqlite3.connect('app.db')
for row in con.execute("select id,name,phone_e164,status,error_message,attempt_count from contacts order by id desc limit 20"):
    print(row)
PY
```

## Testes

### Rodar suíte Python

```bash
cd /Users/mac/Desktop/IA/mass-sender
source .venv/bin/activate
python -m pytest -q
```

### Verificar sintaxe do bridge

```bash
cd /Users/mac/Desktop/IA/mass-sender
node --check wa-bridge/server.js
node --check wa-bridge/fetch-qr.js
```

## Logs e Diagnóstico

### Logs do bridge

Rode o `npm start` em um terminal dedicado. Os eventos aparecem ali:

- `client_building`
- `initialized`
- `authenticated`
- `ready`
- `auth_failure`
- `disconnected`

### Estado detalhado do bridge

```bash
curl -s http://127.0.0.1:3010/session ; echo
```

Campos úteis:

- `connected`
- `state`
- `lastError`
- `lastEvent`
- `history`

### Se o `test-run` falhar

Checklist:

1. confirme `curl -s http://127.0.0.1:3010/health`
2. confirme `curl -s http://127.0.0.1:8000/health`
3. verifique se o contato de teste é real e existe no WhatsApp
4. consulte `send_logs` no SQLite
5. confira o terminal do bridge

## Docker e Evolution API

Esta stack é legada. Use apenas se precisar testar compatibilidade com Evolution.

### Subir

```bash
cd /Users/mac/Desktop/IA/mass-sender
docker compose -f docker-compose.evolution.yml up -d
```

### Parar

```bash
docker compose -f docker-compose.evolution.yml down
```

### Ver status

```bash
docker compose -f docker-compose.evolution.yml ps
docker ps
```

### Ver logs

```bash
docker compose -f docker-compose.evolution.yml logs --tail=120 evolution-api
docker compose -f docker-compose.evolution.yml logs --tail=120 evolution-postgres
docker compose -f docker-compose.evolution.yml logs --tail=120 evolution-redis
```

### Entrar em um container

Se quiser "entrar na Docker" para inspecionar um container:

```bash
docker exec -it evolution-api sh
docker exec -it evolution-postgres sh
docker exec -it evolution-redis sh
```

### Derrubar apenas um serviço

```bash
docker stop evolution-api
docker start evolution-api
```

## Parada dos Serviços

### Parar FastAPI

No terminal do `uvicorn`, use:

```bash
Ctrl+C
```

### Parar o bridge

No terminal do `npm start`, use:

```bash
Ctrl+C
```

### Reiniciar a sessão do bridge

```bash
curl -X POST http://127.0.0.1:3010/session/restart
```

### Trocar de número (desconectar sessão atual)

Use reset completo da sessão para obrigar novo QR e evitar reconexão automática no número antigo:

```bash
curl -X POST http://127.0.0.1:3010/session/reset
```

## Manutenção

### Quando mudar código Python

- reinicie o `uvicorn` se necessário
- rode `python -m pytest -q`

### Quando mudar código do bridge

- pare e suba novamente com `npm start`
- valide com `node --check`

### Quando o WhatsApp desconectar

1. cheque `curl -s http://127.0.0.1:3010/session`
2. se necessário, rode `POST /session/restart`
3. gere QR novamente com `npm run fetch-qr`

## Limitações Atuais

- o console operacional atual já cobre o fluxo completo local
- a UI HTML atual é apenas operacional
- o worker e o bridge precisam permanecer ativos durante o envio
- o banco atual é SQLite local, adequado para MVP e operação simples

## Referência Rápida

### Portas

- `8000`: FastAPI
- `3010`: wa-bridge
- `8080`: Evolution API legada
- `5432`: Postgres da stack legada
- `6379`: Redis da stack legada

### Comandos essenciais

```bash
# bridge
cd wa-bridge && npm start

# qr
cd wa-bridge && npm run fetch-qr && open /tmp/mass-sender-wa-qr.png

# backend
source .venv/bin/activate && uvicorn main:app --reload

# health
curl -s http://127.0.0.1:3010/health ; echo
curl -s http://127.0.0.1:8000/health ; echo

# testes
source .venv/bin/activate && python -m pytest -q
```
