# Guia do Ambiente de Testes (Docker Local)

Este documento descreve como gerenciar o ambiente de desenvolvimento e testes isolado utilizando Docker. Este ambiente replica a infraestrutura da VPS em sua máquina local para validação de funcionalidades.

> **IMPORTANTE:** Toda a operação deste ambiente ocorre dentro do diretório do worktree dedicado:
> `cd .worktrees/local-testing`

---

## 1. Comandos de Inicialização

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
