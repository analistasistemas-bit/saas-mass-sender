const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { loadEnvFile } = require('../lib/env-loader');

test('loadEnvFile reads values without overriding existing env', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'wa-env-'));
  const envPath = path.join(dir, '.env');
  fs.writeFileSync(
    envPath,
    ['BACKEND_INBOUND_WEBHOOK_URL=http://127.0.0.1:8000/webhooks/whatsapp/inbound', 'WA_BRIDGE_HOST=0.0.0.0'].join('\n'),
  );

  delete process.env.BACKEND_INBOUND_WEBHOOK_URL;
  process.env.WA_BRIDGE_HOST = '127.0.0.1';

  loadEnvFile(envPath);

  assert.equal(process.env.BACKEND_INBOUND_WEBHOOK_URL, 'http://127.0.0.1:8000/webhooks/whatsapp/inbound');
  assert.equal(process.env.WA_BRIDGE_HOST, '127.0.0.1');
});
