# Guia de Operações — Mass Sender SaaS na VPS

## Informações gerais

| Item | Valor |
|------|-------|
| Provedor | Hostinger VPS |
| IP da VPS | `76.13.166.179` |
| URL pública | https://mass-sender.daludi.com.br |
| Usuário de deploy | `deploy` |
| Diretório da aplicação | `/opt/mass-sender` |
| Banco de dados | SQLite — Docker volume `mass-sender_app_data` |
| Sessão WhatsApp | Docker volume `mass-sender_wa_sessions` |

---

## Arquitetura dos serviços

```
Internet (HTTPS)
    ↓
Cloudflare (SSL Flexible — termina TLS)
    ↓ HTTP porta 80
Nginx (host) — /etc/nginx/sites-available/mass-sender
    ↓ proxy para 127.0.0.1:8000
Docker container: app (FastAPI/Uvicorn)
    ↓ rede interna Docker (http://wa-bridge:3010)
Docker container: wa-bridge (Node.js + Chromium)
```

---

## Acesso SSH à VPS

```bash
# Do seu Mac:
ssh root@76.13.166.179

# Para operar os containers (usuário deploy):
ssh root@76.13.166.179
su - deploy
cd /opt/mass-sender
```

---

## Containers Docker

### Ver status dos containers

```bash
# Como deploy:
su - deploy
cd /opt/mass-sender
docker compose ps
```

Saída esperada:
```
NAME                      IMAGE                 STATUS
mass-sender-app-1         mass-sender-app       Up X minutes
mass-sender-wa-bridge-1   mass-sender-wa-bridge Up X minutes
```

### Ver logs em tempo real

```bash
# Logs do app (FastAPI):
docker compose logs app -f

# Logs do WhatsApp bridge:
docker compose logs wa-bridge -f

# Logs dos dois juntos:
docker compose logs -f

# Últimas 100 linhas (sem ficar ao vivo):
docker compose logs app --tail=100
docker compose logs wa-bridge --tail=100
```

### Entrar dentro de um container

```bash
# Entrar no container do app (bash):
docker compose exec app bash

# Entrar no container do wa-bridge (bash):
docker compose exec wa-bridge bash

# Sair do container:
exit
```

### Reiniciar serviços

```bash
# Reiniciar tudo:
docker compose restart

# Reiniciar só o app:
docker compose restart app

# Reiniciar só o wa-bridge:
docker compose restart wa-bridge
```

### Parar e iniciar

```bash
# Parar tudo (containers ficam criados mas parados):
docker compose stop

# Iniciar tudo:
docker compose start

# Parar e remover containers (volumes são preservados):
docker compose down

# Subir tudo:
docker compose up -d
```

---

## Deploy manual (sem GitHub Actions)

Quando precisar atualizar manualmente sem fazer push:

```bash
su - deploy
cd /opt/mass-sender

# Baixar código mais recente:
git pull origin main

# Reconstruir e reiniciar:
docker compose build app
docker compose up -d --remove-orphans

# Verificar health:
curl http://127.0.0.1:8000/health
```

---

## Banco de dados (SQLite)

O banco fica dentro do Docker volume `mass-sender_app_data`, montado em `/data/app.db` dentro do container.

### Acessar o banco via SQLite

```bash
# Entrar no container do app:
docker compose exec app bash

# Dentro do container:
sqlite3 /data/app.db

# Comandos úteis no SQLite:
.tables                     # listar tabelas
.schema campaigns           # ver estrutura da tabela
SELECT COUNT(*) FROM campaigns;
SELECT COUNT(*) FROM contacts;
.quit                       # sair
```

### Fazer backup do banco

```bash
# Do host (fora do container):
docker compose exec app sqlite3 /data/app.db ".backup '/data/backup-$(date +%Y%m%d).db'"

# Copiar backup para o host:
docker cp mass-sender-app-1:/data/backup-$(date +%Y%m%d).db ~/backup-$(date +%Y%m%d).db

# Baixar para o Mac:
scp root@76.13.166.179:~/backup-$(date +%Y%m%d).db ~/Desktop/
```

---

## Sessão WhatsApp

A sessão WhatsApp fica no Docker volume `mass-sender_wa_sessions`. **Este volume nunca deve ser apagado** — contém o QR scan e evita precisar reautenticar.

### Verificar status da sessão

```bash
# Via health check interno:
curl http://127.0.0.1:8000/health

# Via wa-bridge diretamente (dentro do container app):
docker compose exec app curl http://wa-bridge:3010/session
```

### WhatsApp desconectou — como reconectar

1. Acesse https://mass-sender.daludi.com.br no browser
2. Faça login
3. Clique em **Reconectar** ou **Escanear QR**
4. Escaneie com o celular

### Resetar sessão completamente (último recurso)

```bash
# Via interface web: login → botão "Reset Sessão"

# Ou via API interna:
docker compose exec app curl -X POST http://wa-bridge:3010/session/reset
```

---

## Nginx

### Arquivos de configuração

| Arquivo | Descrição |
|---------|-----------|
| `/etc/nginx/sites-available/mass-sender` | Config do vhost da aplicação |
| `/etc/nginx/sites-enabled/mass-sender` | Symlink que ativa a config |
| `/etc/nginx/nginx.conf` | Config global do Nginx |

### Comandos do Nginx

```bash
# Verificar sintaxe da config:
nginx -t

# Recarregar config sem derrubar:
systemctl reload nginx

# Reiniciar Nginx:
systemctl restart nginx

# Ver status:
systemctl status nginx

# Ver logs de erro:
tail -f /var/log/nginx/error.log

# Ver logs de acesso:
tail -f /var/log/nginx/access.log
```

### Config atual do vhost

Arquivo: `/etc/nginx/sites-available/mass-sender`

```nginx
server {
    listen 80;
    server_name mass-sender.daludi.com.br;
    client_max_body_size 20M;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
```

---

## Firewall (UFW)

```bash
# Ver regras ativas:
ufw status

# Regras configuradas:
# 22/tcp  — SSH
# 80/tcp  — HTTP (Cloudflare → Nginx)
# 443/tcp — HTTPS (Cloudflare)

# Adicionar regra:
ufw allow PORTA/tcp

# Remover regra:
ufw delete allow PORTA/tcp
```

---

## Volumes Docker

Os dados persistentes ficam em volumes Docker — não são apagados em deploys ou reinicializações.

```bash
# Listar volumes:
docker volume ls

# Detalhes de um volume:
docker volume inspect mass-sender_app_data
docker volume inspect mass-sender_wa_sessions

# Localização física no host:
# /var/lib/docker/volumes/mass-sender_app_data/_data/
# /var/lib/docker/volumes/mass-sender_wa_sessions/_data/
```

**Nunca apague esses volumes** sem fazer backup antes.

---

## CI/CD — Deploy automático (GitHub Actions)

Qualquer push no branch `main` do repositório dispara o deploy automático.

**Repositório:** https://github.com/analistasistemas-bit/saas-mass-sender

**O que o deploy faz:**
1. SSH na VPS como usuário `deploy`
2. `git pull origin main`
3. `docker compose build app`
4. `docker compose up -d --remove-orphans`
5. Health check em `http://127.0.0.1:8000/health`
6. `docker image prune -f`

**Acompanhar deploy:** GitHub → repositório → aba **Actions**

**Secrets configurados no GitHub:**

| Secret | Valor |
|--------|-------|
| `VPS_HOST` | `76.13.166.179` |
| `VPS_USER` | `deploy` |
| `VPS_SSH_PORT` | `22` |
| `VPS_SSH_PRIVATE_KEY` | Chave privada SSH do deploy |

---

## Arquivo .env de produção

Localização: `/opt/mass-sender/.env`
Permissões: `600` (só o usuário deploy lê)

```bash
# Ver conteúdo (como deploy ou root):
cat /opt/mass-sender/.env

# Editar:
nano /opt/mass-sender/.env

# Após editar o .env, reiniciar os containers para aplicar:
docker compose restart
```

**Variáveis configuradas:**

| Variável | Descrição |
|----------|-----------|
| `APP_ADMIN_PASSWORD` | Senha de acesso à interface web |
| `WHATSAPP_PROVIDER` | `bridge` (usa o wa-bridge local) |
| `WA_BRIDGE_API_KEY` | Chave de autenticação entre app e wa-bridge |
| `WA_BRIDGE_PORT` | `3010` |
| `WA_SESSION_NAME` | Nome da sessão WhatsApp |
| `WA_HEADLESS` | `true` (Chromium sem interface gráfica) |

---

## Diagnóstico rápido

### App não responde

```bash
# 1. Containers estão rodando?
su - deploy && cd /opt/mass-sender && docker compose ps

# 2. Health check interno:
curl http://127.0.0.1:8000/health

# 3. Nginx está ok?
systemctl status nginx
nginx -t

# 4. Ver logs de erro:
docker compose logs app --tail=50
```

### WhatsApp não conecta

```bash
# Ver logs do wa-bridge:
docker compose logs wa-bridge --tail=50

# Status da sessão:
docker compose exec app curl http://wa-bridge:3010/session

# Reiniciar o wa-bridge:
docker compose restart wa-bridge
```

### Deploy falhou

```bash
# Ver logs do último deploy no GitHub Actions (aba Actions do repositório)

# Verificar estado dos containers:
docker compose ps

# Ver logs do app após tentativa de deploy:
docker compose logs app --tail=50

# Forçar restart manual:
docker compose restart
```

### Domínio retorna erro 522

Erro 522 = Cloudflare não consegue conectar na VPS.

```bash
# Verificar se Nginx está rodando:
systemctl status nginx

# Verificar se porta 80 está aberta:
ss -tlnp | grep ':80'

# Verificar firewall:
ufw status

# Testar conexão direta (bypass Cloudflare):
curl -H "Host: mass-sender.daludi.com.br" http://76.13.166.179/health
```

Se o teste direto funcionar, o problema é no Cloudflare SSL/TLS (deve estar em **Flexible**).

---

## Localização de todos os arquivos importantes

| O quê | Onde |
|-------|------|
| Código da aplicação | `/opt/mass-sender/` |
| Arquivo de senhas | `/opt/mass-sender/.env` |
| docker-compose.yml | `/opt/mass-sender/docker-compose.yml` |
| Config Nginx | `/etc/nginx/sites-available/mass-sender` |
| Logs Nginx (erro) | `/var/log/nginx/error.log` |
| Logs Nginx (acesso) | `/var/log/nginx/access.log` |
| Banco de dados | Volume Docker `mass-sender_app_data` → `/data/app.db` dentro do container |
| Sessão WhatsApp | Volume Docker `mass-sender_wa_sessions` → `/app/.wwebjs_auth` dentro do container |
| Chave SSH do deploy | `/home/deploy/.ssh/authorized_keys` |
