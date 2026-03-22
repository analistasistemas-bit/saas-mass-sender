# Checklist: Setup VPS + CI/CD (O que você precisa fazer)

> Os arquivos Docker e GitHub Actions já foram criados no repositório.
> Este checklist cobre apenas o que precisa ser feito manualmente: VPS e GitHub.

---

## Status atual

| Item | Status |
|------|--------|
| Subdomínio `mass-sender.daludi.com.br` criado no Cloudflare | ✅ Feito |
| IP da VPS identificado: `76.13.166.179` | ✅ Feito |
| Arquivos Docker criados no repositório | ✅ Feito |
| Workflow GitHub Actions criado | ✅ Feito |

> **Cloudflare Proxy ativo (nuvem laranja):** O Cloudflare gerencia o HTTPS automaticamente.
> Não é necessário instalar certbot na VPS — o SSL já está resolvido pelo Cloudflare.

---

## Passo 1 — Configurar o SSL no Cloudflare

Como o proxy do Cloudflare está ativo, é preciso definir como ele se comunica com a VPS.

No Cloudflare, acesse: **daludi.com.br → SSL/TLS → Overview**

Selecione o modo **Flexible**:
- Cloudflare recebe HTTPS do usuário ✅
- Cloudflare envia HTTP para a VPS (porta 80) — sem precisar de certificado na VPS ✅

---

## Passo 2 — Subir o código para o GitHub

No terminal do Mac, dentro da pasta do projeto:

```bash
git add .
git commit -m "feat: add Docker and CI/CD for VPS deploy"
git push origin main
```

---

## Passo 3 — Instalar Docker na VPS

Conecte na VPS via SSH:

```bash
ssh root@76.13.166.179
```

Depois rode os comandos abaixo, um por vez:

```bash
# Instalar Docker
curl -fsSL https://get.docker.com | sh

# Verificar se instalou corretamente (deve mostrar a versão)
docker --version
docker compose version

# Criar usuário de deploy (mais seguro do que usar root)
useradd -m -s /bin/bash deploy
usermod -aG docker deploy

# Criar pasta da aplicação
mkdir -p /opt/mass-sender
chown deploy:deploy /opt/mass-sender
```

---

## Passo 4 — Gerar chave SSH para o CI/CD

Esta chave vai permitir que o GitHub Actions acesse a VPS automaticamente a cada push.

**No terminal do seu Mac** (não na VPS):

```bash
ssh-keygen -t ed25519 -C "github-deploy-mass-sender" -f ~/.ssh/mass_sender_deploy -N ""
```

Isso cria dois arquivos:
- `~/.ssh/mass_sender_deploy` → chave **privada** (vai para o GitHub)
- `~/.ssh/mass_sender_deploy.pub` → chave **pública** (vai para a VPS)

**Ver a chave pública** (copie todo o resultado):
```bash
cat ~/.ssh/mass_sender_deploy.pub
```

**Na VPS** (conectado como root), cole a chave pública:
```bash
mkdir -p /home/deploy/.ssh

# Substitua o conteudo entre aspas pela sua chave publica copiada acima:
echo "ssh-ed25519 AAAA...sua-chave-aqui... github-deploy-mass-sender" >> /home/deploy/.ssh/authorized_keys

chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh
```

---

## Passo 5 — Configurar os Secrets no GitHub

No GitHub, acesse:
**Repositório → Settings → Secrets and variables → Actions → New repository secret**

Crie os 4 secrets abaixo:

| Nome do Secret | Valor |
|----------------|-------|
| `VPS_HOST` | `76.13.166.179` |
| `VPS_USER` | `deploy` |
| `VPS_SSH_PORT` | `22` |
| `VPS_SSH_PRIVATE_KEY` | Conteúdo completo de `~/.ssh/mass_sender_deploy` |

Para ver a chave privada (copie tudo, incluindo as linhas `-----BEGIN...-----`):
```bash
cat ~/.ssh/mass_sender_deploy
```

---

## Passo 6 — Clonar o repositório e criar o .env na VPS

**Na VPS**, troque para o usuário deploy e clone o repositório:

```bash
su - deploy
git clone https://github.com/analistasistemas-bit/saas-mass-sender.git /opt/mass-sender
```

Criar o arquivo de configuração com as senhas:

```bash
nano /opt/mass-sender/.env
```

Cole o conteúdo abaixo **trocando os valores** pelos reais:

```ini
APP_ADMIN_PASSWORD=CRIE_UMA_SENHA_FORTE_AQUI
WHATSAPP_PROVIDER=bridge
WA_BRIDGE_API_KEY=CRIE_UMA_CHAVE_ALEATORIA_DE_32_CARACTERES
WA_BRIDGE_PORT=3010
WA_SESSION_NAME=mass-sender
WA_HEADLESS=true
```

> **Como gerar uma chave aleatória:** No terminal do Mac: `openssl rand -hex 16`

Salve no nano: `Ctrl+X` → `Y` → `Enter`

Proteger o arquivo (só o dono pode ler):
```bash
chmod 600 /opt/mass-sender/.env
```

---

## Passo 7 — Configurar o Nginx na VPS para receber o Cloudflare

O Cloudflare (com modo Flexible) envia requisições HTTP na porta 80 para a VPS.
Precisamos de um Nginx na VPS que pegue essa requisição e repasse para o container Docker na porta 8000.

**Na VPS, como root:**

```bash
# Instalar Nginx
apt-get update && apt-get install -y nginx

# Criar configuração para o subdominio
nano /etc/nginx/sites-available/mass-sender
```

Cole o conteúdo abaixo:

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

Salve (`Ctrl+X` → `Y` → `Enter`) e ative:

```bash
ln -s /etc/nginx/sites-available/mass-sender /etc/nginx/sites-enabled/
nginx -t
systemctl reload nginx
```

---

## Passo 8 — Primeiro build e inicialização

**Na VPS**, como usuário deploy:

```bash
cd /opt/mass-sender
docker compose up -d --build
```

Este comando vai demorar alguns minutos na primeira vez (baixa imagens e instala dependências).

Verificar se ambos os containers estão rodando:
```bash
docker compose ps
# Deve mostrar "app" e "wa-bridge" com status "running"
```

Testar se o app está respondendo internamente:
```bash
curl http://127.0.0.1:8000/health
# Deve retornar algo como: {"status": "ok", ...}
```

Testar via domínio (após Nginx e Cloudflare configurados):
```bash
curl https://mass-sender.daludi.com.br/health
```

---

## Passo 9 — Escanear o QR do WhatsApp

Acesse pelo navegador:

```
https://mass-sender.daludi.com.br
```

Faça login com a senha definida no `.env` e procure a opção de conectar o WhatsApp. Um QR Code vai aparecer — escaneie com o WhatsApp no celular (igual ao WhatsApp Web).

---

## Passo 10 — Testar o deploy automático

Faça qualquer mudança pequena no código e faça push:

```bash
git add .
git commit -m "test: testar CI/CD"
git push origin main
```

Acesse no GitHub: **Repositório → Actions** e acompanhe o deploy acontecendo automaticamente. Deve levar cerca de 2–3 minutos e mostrar tudo verde.

---

## Comandos úteis no dia a dia (na VPS)

```bash
# Sempre entre como deploy primeiro:
su - deploy
cd /opt/mass-sender

# Ver status dos containers
docker compose ps

# Ver logs do app em tempo real
docker compose logs app -f

# Ver logs do WhatsApp bridge em tempo real
docker compose logs wa-bridge -f

# Reiniciar tudo manualmente
docker compose restart

# Parar tudo
docker compose down
```
