# Design: Ambiente de Teste Local via Docker

## 1. Visão Geral
Este design descreve a configuração de um ambiente de desenvolvimento e teste local para o projeto Mass Sender SaaS, utilizando Docker para garantir paridade com o ambiente de produção (VPS).

## 2. Componentes do Sistema
- **app**: Backend FastAPI (Python) que processa CSVs, gerencia campanhas e orquestra envios.
- **wa-bridge**: Microserviço Node.js que gerencia a conexão com o WhatsApp via `whatsapp-web.js`.
- **Volumes**:
  - `app_data`: Persistência do banco SQLite.
  - `wa_sessions`: Persistência das sessões do WhatsApp (QR scan).

## 3. Configuração de Rede e Portas
- **App (FastAPI)**: Host `127.0.0.1`, Porta `8000`.
- **Bridge (Node.js)**: Host interno `wa-bridge`, Porta `3010`.

## 4. Fluxo de Execução Local
1. Criação do arquivo `.env` a partir do `.env.example`.
2. Execução de `docker compose build` para atualizar as imagens locais.
3. Execução de `docker compose up -d` para subir os serviços.
4. Verificação de logs via `docker compose logs -f`.

## 5. Riscos e Mitigações
- **Conflito de Porta**: Se a porta 8000 estiver ocupada, será necessário alterar o mapeamento no `docker-compose.yml`.
- **Memória do Chromium**: O container `wa-bridge` exige `shm_size: 1gb` para rodar o navegador headless de forma estável.

## 6. Critérios de Sucesso
- Acessar `http://localhost:8000` com sucesso.
- Status do Bridge retornar "conectado" após o scan do QR Code.
