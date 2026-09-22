const { defineConfig } = require('@playwright/test');
const path = require('path');
const fs = require('fs');

const projectPython = fs.existsSync(path.join(__dirname, '.venv', 'bin', 'uvicorn'))
  ? path.join(__dirname, '.venv', 'bin', 'uvicorn')
  : path.resolve(__dirname, '..', '..', '.venv', 'bin', 'uvicorn');

module.exports = defineConfig({
  testDir: './tests/e2e',
  timeout: 60_000,
  retries: 0,
  use: {
    baseURL: 'http://127.0.0.1:8765',
    headless: true,
    channel: 'chrome',
  },
  webServer: {
    command:
      `bash -lc 'rm -f /tmp/mass-sender-e2e.db /tmp/mass-sender-e2e.db-shm /tmp/mass-sender-e2e.db-wal && APP_ADMIN_PASSWORD=admin123 DB_PATH=/tmp/mass-sender-e2e.db WHATSAPP_PROVIDER=bridge WA_BRIDGE_BASE_URL=http://127.0.0.1:3999 ${projectPython} main:app --port 8765'`,
    url: 'http://127.0.0.1:8765/health',
    timeout: 120_000,
    reuseExistingServer: false,
  },
});
