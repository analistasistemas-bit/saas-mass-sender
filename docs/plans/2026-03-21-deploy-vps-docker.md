# Plano: Deploy SaaS em Docker na VPS (Hostinger) + CI/CD GitHub Actions

## Context

O projeto roda localmente no macbook (FastAPI + wa-bridge Node.js). A VPS já tem o OpenClaw instalado (acessado por porta específica, ex: 2083). Para evitar conflitos, toda a aplicação será isolada em Docker. O acesso público será via subdomínio `sender.daludi.com.br` com SSL — sem mexer em nada do OpenClaw.

---

## Arquitetura final

```
Internet
    ↓ https://sender.daludi.com.br
OpenClaw/Nginx do host (porta 80/443)
    ↓ reverse proxy → 127.0.0.1:8000
Docker container: app (FastAPI)
    ↓ rede interna Docker
Docker container: wa-bridge (Node.js + Chromium)
```

- **OpenClaw gerencia o Nginx** nas portas 80/443 → pedimos a ele para criar um subdomínio com reverse proxy
- **app** expõe apenas `127.0.0.1:8000` no host
- **wa-bridge** fica 100% interno à rede Docker
- Sessão WhatsApp e banco SQLite persistem em Docker volumes

---

## Por que subdomínio e não subpasta?

- `daludi.com.br/saas-mass-sender` = **subpasta** → exigiria reconfigurar todas as rotas do FastAPI com prefixo `/saas-mass-sender` (mudanças de código)
- `sender.daludi.com.br` = **subdomínio** → o app funciona sem nenhuma mudança de código, como se fosse um site independente

**Subdomínio recomendado:** `sender.daludi.com.br` (ou `saas.daludi.com.br`, `app.daludi.com.br` — você escolhe)

---

## Fase 0 — Configurar DNS (antes de qualquer coisa)

### 0.1 Descobrir o IP da sua VPS

No painel da Hostinger, o IP da VPS aparece no dashboard. Ex: `123.456.789.10`

### 0.2 Criar o subdomínio no DNS do daludi.com.br

Onde o domínio `daludi.com.br` está registrado (Registro.br, Hostinger, outro registrador):

1. Entrar no painel de DNS do domínio
2. Criar um registro tipo **A**:
   - **Nome/Host**: `sender`
   - **Valor/Destino**: `IP_DA_SUA_VPS` (ex: `123.456.789.10`)
   - **TTL**: 3600 (1 hora)
3. Aguardar propagação: 5–60 minutos

Verificar se propagou:
```bash
# No seu Mac:
nslookup sender.daludi.com.br
# Deve retornar o IP da VPS
```

---

## Fase 1 — Arquivos a criar no repositório

### 1.1 Dockerfile (raiz do projeto)

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--log-level", "info"]
```

### 1.2 wa-bridge/Dockerfile

```dockerfile
FROM node:20-slim

RUN apt-get update && apt-get install -y \
    chromium \
    fonts-noto-color-emoji \
    fonts-liberation \
    libgbm1 \
    libasound2 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxss1 \
    libgtk-3-0 \
    --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package*.json ./
RUN PUPPETEER_SKIP_DOWNLOAD=true npm install --omit=dev

COPY . .

ENV WA_EXECUTABLE_PATH=/usr/bin/chromium
ENV WA_HEADLESS=true
ENV WA_BRIDGE_HOST=0.0.0.0

CMD ["node", "server.js"]
```

### 1.3 docker-compose.yml (raiz do projeto)

```yaml
services:
  wa-bridge:
    build: ./wa-bridge
    restart: unless-stopped
    env_file: .env
    environment:
      - WA_BRIDGE_HOST=0.0.0.0
    volumes:
      - wa_sessions:/app/.wwebjs_auth
    networks:
      - internal
    shm_size: 1gb
    security_opt:
      - seccomp=unconfined

  app:
    build: .
    restart: unless-stopped
    env_file: .env
    environment:
      - WA_BRIDGE_BASE_URL=http://wa-bridge:3010
      - DB_PATH=/data/app.db
    ports:
      - "127.0.0.1:8000:8000"
    volumes:
      - app_data:/data
    depends_on:
      - wa-bridge
    networks:
      - internal

volumes:
  wa_sessions:
  app_data:

networks:
  internal:
    driver: bridge
```

### 1.4 .dockerignore (raiz do projeto)

```
.env
.env.*
venv/
__pycache__/
*.pyc
.pytest_cache/
tests/
.git/
app.db
wa-bridge/node_modules/
wa-bridge/.wwebjs_auth/
.github/
docs/
```

### 1.5 .github/workflows/deploy.yml

```yaml
name: Deploy to VPS

on:
  push:
    branches: [main]

concurrency:
  group: deploy-production
  cancel-in-progress: false

jobs:
  deploy:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4

      - uses: webfactory/ssh-agent@v0.9.0
        with:
          ssh-private-key: ${{ secrets.VPS_SSH_PRIVATE_KEY }}

      - name: Add VPS to known hosts
        run: ssh-keyscan -p ${{ secrets.VPS_SSH_PORT }} -H ${{ secrets.VPS_HOST }} >> ~/.ssh/known_hosts

      - name: Deploy
        env:
          VPS_HOST: ${{ secrets.VPS_HOST }}
          VPS_USER: ${{ secrets.VPS_USER }}
          VPS_PORT: ${{ secrets.VPS_SSH_PORT }}
        run: |
          ssh -p "$VPS_PORT" "$VPS_USER@$VPS_HOST" 'bash -s' << 'ENDSSH'
            set -euo pipefail
            APP_DIR="/opt/mass-sender"

            echo "=== [1/4] Git pull ==="
            cd "$APP_DIR"
            git fetch --all
            git reset --hard origin/main

            echo "=== [2/4] Build e subir containers ==="
            docker compose build app
            docker compose up -d --remove-orphans

            echo "=== [3/4] Health check ==="
            sleep 10
            HTTP=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/health)
            if [ "$HTTP" != "200" ]; then
              echo "FALHA: health check retornou $HTTP"
              docker compose logs app --tail=50
              exit 1
            fi
            echo "Deploy OK. HTTP: $HTTP"

            echo "=== [4/4] Limpeza ==="
            docker image prune -f
          ENDSSH
```

### 1.6 Correção em wa-bridge/server.js

Localizar o `server.listen(port, ...)` e adicionar suporte ao env `WA_BRIDGE_HOST`:

```js
const host = process.env.WA_BRIDGE_HOST || '127.0.0.1';
server.listen(port, host, () => {
  console.log(`wa-bridge listening on ${host}:${port}`);
});
```

---

## Fase 2 — Setup da VPS (como root via SSH)

### 2.1 Instalar Docker

```bash
curl -fsSL https://get.docker.com | sh
docker --version
docker compose version
```

### 2.2 Criar usuário deploy

```bash
useradd -m -s /bin/bash deploy
usermod -aG docker deploy
```

### 2.3 SSH key para CI/CD

**No seu Mac:**
```bash
ssh-keygen -t ed25519 -C "github-deploy-mass-sender" -f ~/.ssh/mass_sender_deploy -N ""
cat ~/.ssh/mass_sender_deploy      # → GitHub Secret: VPS_SSH_PRIVATE_KEY
cat ~/.ssh/mass_sender_deploy.pub  # → copiar para a VPS
```

**Na VPS:**
```bash
mkdir -p /home/deploy/.ssh
echo "ssh-ed25519 AAAA...sua-chave-publica..." >> /home/deploy/.ssh/authorized_keys
chmod 700 /home/deploy/.ssh && chmod 600 /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh
```

**GitHub** → Settings → Secrets and variables → Actions:

| Secret | Valor |
|--------|-------|
| `VPS_HOST` | IP da VPS |
| `VPS_USER` | `deploy` |
| `VPS_SSH_PORT` | `22` |
| `VPS_SSH_PRIVATE_KEY` | Conteúdo de `~/.ssh/mass_sender_deploy` |

### 2.4 Clonar e configurar

```bash
mkdir -p /opt/mass-sender
chown deploy:deploy /opt/mass-sender

su - deploy
git clone https://github.com/SEU_USER/SEU_REPO.git /opt/mass-sender
```

Criar `/opt/mass-sender/.env`:
```bash
chmod 600 /opt/mass-sender/.env
```

Conteúdo:
```ini
APP_ADMIN_PASSWORD=SENHA_FORTE_AQUI
WHATSAPP_PROVIDER=bridge
WA_BRIDGE_API_KEY=CHAVE_ALEATORIA_32_CHARS
WA_BRIDGE_PORT=3010
WA_SESSION_NAME=mass-sender
WA_HEADLESS=true
```

> `DB_PATH` e `WA_BRIDGE_BASE_URL` são definidos no `docker-compose.yml` diretamente — não precisa no `.env`.

### 2.5 Primeiro build

```bash
su - deploy
cd /opt/mass-sender
docker compose up -d --build
docker compose ps      # ambos "running"
docker compose logs -f
```

---

## Fase 3 — Subdomínio + SSL via OpenClaw

Como o OpenClaw acessa seu painel por uma porta específica, ele provavelmente gerencia o Nginx nas portas 80/443 internamente. O passo a passo depende do painel, mas a lógica é:

### 3.1 Criar o subdomínio no OpenClaw

No painel do OpenClaw:
1. Ir em **Domínios** → **Adicionar subdomínio**
2. Criar: `sender.daludi.com.br`
3. Tipo: **Reverse Proxy** (ou "Proxy Pass")
4. Destino: `http://127.0.0.1:8000`

### 3.2 SSL no OpenClaw

No painel:
1. Selecionar o subdomínio `sender.daludi.com.br`
2. Clicar em **SSL** → **Let's Encrypt**
3. Emitir certificado

Após isso, `https://sender.daludi.com.br` já aponta para o container FastAPI.

### 3.3 Se o OpenClaw não tiver opção de reverse proxy

Instalar e configurar Nginx manualmente:

```bash
# Verificar se o Nginx do sistema está ativo:
systemctl status nginx

# Se estiver, criar um vhost:
nano /etc/nginx/sites-available/mass-sender
```

```nginx
server {
    listen 80;
    server_name sender.daludi.com.br;
    client_max_body_size 20M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
```

```bash
ln -s /etc/nginx/sites-available/mass-sender /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

# SSL:
apt-get install -y certbot python3-certbot-nginx
certbot --nginx -d sender.daludi.com.br --email seu@email.com --agree-tos --non-interactive --redirect
```

---

## Fase 4 — Primeira sessão WhatsApp

```bash
# Na VPS, ver o QR via logs:
docker compose logs wa-bridge | grep -A5 "QR"

# Ou copiar QR para o Mac:
ssh deploy@IP_VPS "docker compose -f /opt/mass-sender/docker-compose.yml exec app \
  curl http://wa-bridge:3010/session/qr" > /tmp/qr.json

# Ou: acessar https://sender.daludi.com.br e escanear pelo painel web
```

---

## Verificação final

```bash
# Containers rodando
docker compose ps

# Health check direto
curl http://127.0.0.1:8000/health

# Via domínio (após DNS + SSL)
curl https://sender.daludi.com.br/health

# Logs
docker compose logs -f app
docker compose logs -f wa-bridge

# Testar CI/CD: push no main → acompanhar no GitHub Actions
```

---

## Resumo dos arquivos a criar/modificar

| Arquivo | Ação |
|---------|------|
| `Dockerfile` | **Criar** |
| `wa-bridge/Dockerfile` | **Criar** |
| `docker-compose.yml` | **Criar** |
| `.dockerignore` | **Criar** |
| `.github/workflows/deploy.yml` | **Criar** |
| `wa-bridge/server.js` | **Modificar** — `WA_BRIDGE_HOST` no `server.listen()` |
