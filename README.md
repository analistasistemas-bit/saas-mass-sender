# WhatsApp Campaign Sender (MVP)

MVP local para envio em massa via WhatsApp usando CSV, FastAPI, SQLite e backend de envio configuravel.
O caminho principal de execução hoje é `FastAPI + wa-bridge (Node + whatsapp-web.js)`.
O sistema já inclui um frontend operacional completo em `templates/` e `static/`, com fluxo guiado para conexão, validação, teste, envio e acompanhamento.

Documentação operacional completa:

- [Operations Guide](/Users/mac/Desktop/IA/mass-sender/docs/OPERATIONS.md)
- [Guia de Uso do Aplicativo](/Users/mac/Desktop/IA/mass-sender/docs/USER_GUIDE.md)

## Recursos implementados

- Criação de campanhas (`draft`, `ready`, `running`, `paused`, `cancelled`, `completed`)
- Upload CSV com validação UTF-8 e colunas `nome,telefone,email`
- Normalização de telefone BR para `+55...`
- Simulação de campanha com preview e estimativa
- Envio de teste obrigatório antes do envio real
- Worker persistente baseado em banco
- Retry para erros temporários (até 2 retries)
- Pausa, retomada e cancelamento
- Monitoramento por polling (4s)
- Exportação CSV de falhas
- Login com senha única via `.env`
- Backend local padrão com `whatsapp-web.js`
- Compatibilidade legada com Evolution API

## Estrutura

- `main.py`
- `database.py`
- `models.py`
- `schemas.py`
- `services/`
- `utils/`
- `templates/`
- `static/`
- `tests/`

## Arquitetura Atual

- `FastAPI` concentra campanhas, contatos, fila, worker e regras de negócio.
- `wa-bridge/` mantém a sessão do WhatsApp Web e expõe endpoints mínimos para envio e healthcheck.
- `templates/` e `static/` implementam o console operacional atual usado no fluxo local.

## Configuração

### Fluxo padrão: bridge local com Node.js

Versão de Node recomendada para o `wa-bridge`:

- `Node 20 LTS` recomendado
- `Node 22 LTS` aceito
- `Node 25+` não suportado

1. Copie `.env.example` para `.env`.
2. Ajuste `.env` com o bridge como provider padrão:

```env
APP_ADMIN_PASSWORD=admin123
DB_PATH=app.db
WHATSAPP_PROVIDER=bridge
WA_BRIDGE_BASE_URL=http://127.0.0.1:3010
WA_BRIDGE_API_KEY=
```

3. Instale dependências Python:

```bash
python3 -m pip install -r requirements.txt
```

4. Instale dependências do bridge:

```bash
cd wa-bridge
npm install
```

5. Suba o bridge:

```bash
npm start
```

6. Em outro terminal, acompanhe a sessão:

```bash
curl http://127.0.0.1:3010/health
curl http://127.0.0.1:3010/session/qr
```

7. Salve e abra o QR:

```bash
cd wa-bridge
npm run fetch-qr
open /tmp/mass-sender-wa-qr.png
```

8. Depois que o WhatsApp estiver conectado, suba o backend Python:

```bash
cd ..
uvicorn main:app --reload
```

### Opção legada: Evolution API

Use esta opção apenas se houver necessidade explícita de manter compatibilidade com Evolution.

1. Suba a Evolution API local:

```bash
docker compose -f docker-compose.evolution.yml up -d
```

2. Crie/conecte a instância no Evolution (QR code) e obtenha a `API KEY`.
3. Ajuste `.env`:

- `WHATSAPP_PROVIDER=evolution`
- `EVOLUTION_BASE_URL`
- `EVOLUTION_INSTANCE`
- `EVOLUTION_API_KEY`
- `APP_ADMIN_PASSWORD`

4. Rode o backend:

```bash
uvicorn main:app --reload
```

## Uso rápido

1. Abra `http://localhost:8000/login`
2. Entre com `APP_ADMIN_PASSWORD`
3. Na home, conecte o número no bloco `Canal WhatsApp`
4. Crie campanha
5. Ajuste a mensagem com `{{nome}}`
6. Faça upload do CSV
7. Clique em `Simular campanha`
8. Clique em `Enviar teste`
9. Clique em `Iniciar campanha`

Para o passo a passo completo de operação:

- [Guia de Uso do Aplicativo](/Users/mac/Desktop/IA/mass-sender/docs/USER_GUIDE.md)

## CSV esperado

```csv
nome,telefone,email
Maria,(11)98888-7777,maria@email.com
```

Formato legado tambem suportado:

```csv
,"NOME_CLIENTE","TELEFONE","E_MAIL"
1,"EMMET DOUGLAS DOS SANTOS FEIT","5581992049923",""
2,"RWC WERI CONFECCAO","5581984299667",""
```

## Testes

```bash
./.venv/bin/pytest -q
npx playwright test
```

Detalhes da resolucao do ambiente de testes:

- [Resolucao de Testes](/Users/mac/Desktop/IA/mass-sender/docs/TESTING_RESOLUTION.md)

## Observações

- Projeto otimizado para execução local e simplicidade operacional.
- Sem Redis/Celery e sem WebSocket.
- O frontend operacional atual foi redesenhado para uso local e cobre o fluxo de ponta a ponta.
- Se o backend de envio falhar, o sistema preserva estado e tenta retry quando aplicável.
- O bridge Node mantém sessão local do WhatsApp Web e expõe apenas `/health`, `/session/qr`, `/session/restart` e `/messages/send-text`.
# saas-mass-sender
