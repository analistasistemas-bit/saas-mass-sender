FROM node:20-slim

# Instala Chromium e todas as dependencias necessarias para o Puppeteer rodar em container
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

# Instala dependencias Node sem baixar o Chromium do Puppeteer (usa o do sistema)
COPY package*.json ./
RUN PUPPETEER_SKIP_DOWNLOAD=true npm install --omit=dev

COPY . .

# Aponta para o Chromium do sistema
ENV WA_EXECUTABLE_PATH=/usr/bin/chromium
ENV WA_HEADLESS=true
# Dentro do container Docker, ouve em todas as interfaces da rede interna
ENV WA_BRIDGE_HOST=0.0.0.0

CMD ["node", "server.js"]
