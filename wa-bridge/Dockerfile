FROM node:20-slim

# Shared libraries for Puppeteer's bundled Chrome. Do not install Debian
# chromium: that build is not the Chrome revision Puppeteer/whatsapp-web.js
# was tested with, and it stalls after `authenticated` without `ready`.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    fonts-liberation \
    fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json package-lock.json ./
# Downloads the Chrome build pinned by puppeteer (via whatsapp-web.js).
# Do not set PUPPETEER_SKIP_DOWNLOAD or PUPPETEER_EXECUTABLE_PATH.
RUN npm ci --omit=dev \
    && apt-get update \
    && npx puppeteer browsers install chrome --install-deps \
    && rm -rf /var/lib/apt/lists/*

COPY . .

# Safe default: puppeteer.executablePath() inside server.js.
# Set WA_EXECUTABLE_PATH only to a Puppeteer-compatible Chrome binary.
# /usr/bin/chromium is not a supported default.
ENV WA_HEADLESS=true
# Inside Docker, listen on the internal network.
ENV WA_BRIDGE_HOST=0.0.0.0

CMD ["node", "server.js"]
