const express = require('express');
const http = require('node:http');
const path = require('node:path');
const fs = require('node:fs/promises');
const QRCode = require('qrcode');
const { Client, LocalAuth } = require('whatsapp-web.js');
const { loadEnvFile } = require('./lib/env-loader');
const { isBrowserAlreadyRunningError, extractProfileOwnerPid, releaseSessionBrowserLock } = require('./lib/process-guard');
const { shouldForwardInboundMessage, buildInboundPayload, publishInboundWebhook } = require('./lib/inbound-webhook');
const { resolveChatIdForPhone } = require('./lib/recipient-resolver');

loadEnvFile(path.resolve(__dirname, '.env'));
loadEnvFile(path.resolve(__dirname, '../.env'));

const app = express();
app.use(express.json({ limit: '1mb' }));

function assertSupportedNodeVersion() {
  const [major] = process.versions.node.split('.').map((part) => Number(part));
  if (major < 18 || major >= 25) {
    console.error(
      `[wa-bridge] unsupported Node.js version ${process.version}. ` +
        'Use Node 20 LTS (recommended) or Node 22 LTS for whatsapp-web.js/puppeteer stability.'
    );
    process.exit(1);
  }
}

assertSupportedNodeVersion();

const port = Number(process.env.WA_BRIDGE_PORT || 3010);
const apiKey = process.env.WA_BRIDGE_API_KEY || '';
const sessionName = process.env.WA_SESSION_NAME || 'mass-sender';
const dataPath = path.resolve(process.env.WA_DATA_PATH || '.wwebjs_auth');
const userDataDir = path.resolve(dataPath, `session-${sessionName}`);
const headless = process.env.WA_HEADLESS !== 'false';
const executablePath = process.env.WA_EXECUTABLE_PATH || '';
const inboundWebhookUrl = process.env.BACKEND_INBOUND_WEBHOOK_URL || '';
const inboundWebhookToken = process.env.BACKEND_INBOUND_WEBHOOK_TOKEN || '';

const state = {
  connected: false,
  state: 'starting',
  lastError: null,
  qrDataUrl: null,
  phone: null,
  lastEvent: 'boot',
  history: [],
};
let retryTimer = null;
let shuttingDown = false;

function track(event, extra = {}) {
  state.lastEvent = event;
  const entry = {
    at: new Date().toISOString(),
    event,
    ...extra,
  };
  state.history = [entry, ...state.history].slice(0, 20);
  if (Object.keys(extra).length) {
    console.log(`[wa-bridge] ${event}`, extra);
  } else {
    console.log(`[wa-bridge] ${event}`);
  }
}

function authMiddleware(req, res, next) {
  if (!apiKey) {
    next();
    return;
  }

  if (req.get('x-api-key') !== apiKey) {
    res.status(401).json({ ok: false, message: 'invalid api key' });
    return;
  }

  next();
}

function normalizePhone(phone) {
  return String(phone || '').replace(/\D/g, '');
}

async function buildClient(options = {}) {
  const puppeteer = {
    headless,
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-gpu',
      '--disable-extensions',
      '--disable-background-networking',
      '--disable-default-apps',
      '--disable-sync',
      '--disable-translate',
      '--metrics-recording-only',
      '--no-first-run',
      '--safebrowsing-disable-auto-update',
      '--single-process',
      '--js-flags=--max-old-space-size=256',
    ],
  };
  if (executablePath) {
    puppeteer.executablePath = executablePath;
  }

  track('client_building', { headless, executablePath: executablePath || 'bundled' });

  const client = new Client({
    authStrategy: new LocalAuth({ clientId: sessionName, dataPath }),
    puppeteer,
  });

  client.on('qr', async (qr) => {
    state.connected = false;
    state.state = 'qr_ready';
    state.lastError = null;
    state.qrDataUrl = await QRCode.toDataURL(qr);
    track('qr');
  });

  client.on('authenticated', () => {
    state.state = 'authenticated';
    state.lastError = null;
    track('authenticated');
  });

  client.on('ready', async () => {
    state.connected = true;
    state.state = 'ready';
    state.qrDataUrl = null;

    try {
      const info = client.info || {};
      state.phone = info.wid ? info.wid.user : null;
    } catch (_err) {
      state.phone = null;
    }
    track('ready', { phone: state.phone });
  });

  client.on('auth_failure', (message) => {
    state.connected = false;
    state.state = 'auth_failure';
    state.lastError = message || 'authentication failed';
    track('auth_failure', { message: state.lastError });
  });

  client.on('disconnected', (reason) => {
    state.connected = false;
    state.state = 'disconnected';
    state.lastError = String(reason || 'disconnected');
    track('disconnected', { reason: state.lastError });
  });

  client.on('change_state', (value) => {
    state.state = String(value || 'unknown').toLowerCase();
    track('change_state', { value: state.state });
  });

  client.on('loading_screen', (percent, message) => {
    track('loading_screen', { percent, message });
  });

  client.on('message', async (message) => {
    if (!shouldForwardInboundMessage(message)) {
      return;
    }

    const payload = buildInboundPayload(message);
    try {
      const result = await publishInboundWebhook(payload, {
        backendUrl: inboundWebhookUrl,
        token: inboundWebhookToken,
      });
      track('inbound_webhook_sent', {
        wa_message_id: payload.wa_message_id,
        status: result.status || 0,
        ok: result.ok,
      });
    } catch (error) {
      track('inbound_webhook_failed', {
        wa_message_id: payload.wa_message_id,
        message: String(error && error.message ? error.message : error).slice(0, 200),
      });
    }
  });

  try {
    await client.initialize();
    track('initialized');
  } catch (error) {
    state.lastError = String(error && error.message ? error.message : error);
    state.state = 'initialize_failed';
    track('initialize_failed', { message: state.lastError });

    if (!options.recovered && isBrowserAlreadyRunningError(error)) {
      track('stale_browser_detected', { userDataDir });
      const errorPid = extractProfileOwnerPid(error);
      const recovery = await releaseSessionBrowserLock(userDataDir, { errorPid });
      track('stale_browser_cleanup', recovery);
      if (recovery.remaining.length === 0) {
        track('retry_after_cleanup');
        return buildClient({ recovered: true });
      }
    }

    throw error;
  }
  return client;
}

function scheduleRetry(reason) {
  if (retryTimer) return;
  const delayMs = Number(process.env.WA_RETRY_MS || 5000);
  track('init_retry_scheduled', { delayMs, reason: String(reason || '').slice(0, 160) });
  retryTimer = setTimeout(() => {
    retryTimer = null;
    startClientBuild();
  }, delayMs);
}

function startClientBuild() {
  state.connected = false;
  if (state.state !== 'restarting') {
    state.state = 'starting';
  }
  clientPromise = buildClient().catch((error) => {
    state.lastError = String(error && error.message ? error.message : error);
    state.state = 'initialize_failed';
    track('init_retry_waiting', { message: state.lastError });
    scheduleRetry(error);
    return null;
  });
}

let clientPromise = Promise.resolve(null);
startClientBuild();

async function getClient() {
  const client = await clientPromise;
  if (!client) {
    const message = state.lastError || `whatsapp client not ready (${state.state})`;
    const error = new Error(message);
    error.statusCode = 503;
    throw error;
  }
  return client;
}

async function probeExistingBridge() {
  try {
    const response = await fetch(`http://127.0.0.1:${port}/health`);
    if (!response.ok) {
      return { ok: false, status: response.status };
    }
    const payload = await response.json();
    return { ok: payload.provider === 'bridge', payload };
  } catch (_error) {
    return { ok: false };
  }
}

async function closeClient() {
  try {
    const client = await clientPromise;
    if (client) {
      await client.destroy();
    }
  } catch (_error) {
    // best effort shutdown
  }
}

async function destroyCurrentClient() {
  try {
    const client = await clientPromise;
    if (!client) return;
    try {
      await client.logout();
      track('logout');
    } catch (_error) {
      // logout may fail if not authenticated; destroy still required
    }
    await client.destroy();
  } catch (_error) {
    // best effort
  }
}

async function resetSessionState() {
  state.connected = false;
  state.state = 'restarting';
  state.qrDataUrl = null;
  state.lastError = null;
  state.phone = null;
  if (retryTimer) {
    clearTimeout(retryTimer);
    retryTimer = null;
  }
}

function scheduleShutdown(signal) {
  if (shuttingDown) return;
  shuttingDown = true;
  track('shutdown_requested', { signal });
  if (retryTimer) {
    clearTimeout(retryTimer);
    retryTimer = null;
  }
  Promise.resolve()
    .then(() => closeClient())
    .finally(() => {
      server.close(() => {
        process.exit(0);
      });
      setTimeout(() => process.exit(0), 1500).unref();
    });
}

app.get('/health', authMiddleware, (_req, res) => {
  res.json({
    ok: true,
    provider: 'bridge',
    connected: state.connected,
    state: state.state,
    phone: state.phone,
    hasQr: Boolean(state.qrDataUrl),
    lastError: state.lastError,
    lastEvent: state.lastEvent,
  });
});

app.get('/session', authMiddleware, (_req, res) => {
  res.json({
    ok: true,
    connected: state.connected,
    state: state.state,
    phone: state.phone,
    hasQr: Boolean(state.qrDataUrl),
    lastError: state.lastError,
    lastEvent: state.lastEvent,
    history: state.history,
  });
});

app.get('/session/qr', authMiddleware, (_req, res) => {
  if (!state.qrDataUrl) {
    res.status(404).json({ ok: false, message: 'qr not available', state: state.state });
    return;
  }

  res.json({ ok: true, state: state.state, base64: state.qrDataUrl });
});

app.post('/session/restart', authMiddleware, async (_req, res) => {
  try {
    await destroyCurrentClient();
  } catch (_err) {
    // ignore destroy failures during restart
  }
  await resetSessionState();
  startClientBuild();

  res.json({ ok: true, message: 'session restarting' });
});

app.post('/session/reset', authMiddleware, async (_req, res) => {
  try {
    await destroyCurrentClient();
  } catch (_err) {
    // best effort
  }

  const lockCleanup = await releaseSessionBrowserLock(userDataDir);
  const sessionPath = path.resolve(dataPath, `session-${sessionName}`);
  await fs.rm(sessionPath, { recursive: true, force: true });
  track('session_reset', { sessionPath, lockCleanup });

  await resetSessionState();
  startClientBuild();
  res.json({ ok: true, message: 'session reset', lockCleanup });
});

app.post('/numbers/resolve', authMiddleware, async (req, res) => {
  const phone = normalizePhone(req.body.phone);

  if (!phone) {
    res.status(400).json({ ok: false, message: 'phone is required' });
    return;
  }

  try {
    const client = await getClient();
    let queryWid = null;
    let isRegistered = null;
    let lidInfo = null;
    let diagnostics = {};

    try {
      queryWid = await client.getNumberId(phone);
    } catch (error) {
      diagnostics.getNumberId = String(error && error.message ? error.message : error);
    }

    try {
      isRegistered = await client.isRegisteredUser(phone);
    } catch (error) {
      diagnostics.isRegisteredUser = String(error && error.message ? error.message : error);
    }

    try {
      [lidInfo] = await client.getContactLidAndPhone([phone]);
    } catch (error) {
      diagnostics.getContactLidAndPhone = String(error && error.message ? error.message : error);
    }

    res.json({
      ok: true,
      phone,
      queryWid: queryWid ? queryWid._serialized || queryWid : null,
      isRegistered,
      lid: lidInfo?.lid || null,
      pn: lidInfo?.pn || null,
      diagnostics,
    });
  } catch (error) {
    state.lastError = String(error && error.message ? error.message : error);
    const statusCode = Number(error && error.statusCode ? error.statusCode : 502);
    res.status(statusCode).json({ ok: false, message: state.lastError, state: state.state });
  }
});

app.post('/messages/send-text', authMiddleware, async (req, res) => {
  const phone = normalizePhone(req.body.phone);
  const text = String(req.body.text || '').trim();

  if (!phone || !text) {
    res.status(400).json({ ok: false, message: 'phone and text are required' });
    return;
  }

  if (!state.connected) {
    res.status(409).json({ ok: false, message: 'whatsapp session not connected', state: state.state });
    return;
  }

  try {
    const client = await getClient();
    const chatId = await resolveChatIdForPhone(client, phone);
    await client.sendMessage(chatId, text);
    state.lastError = null; // Limpa erro se o envio funcionou
    res.json({ ok: true, chatId });
  } catch (error) {
    state.lastError = String(error && error.message ? error.message : error);
    const statusCode = Number(error && error.statusCode ? error.statusCode : 502);
    res.status(statusCode).json({ ok: false, message: state.lastError, state: state.state });
  }
});

const server = http.createServer(app);

server.on('error', async (error) => {
  if (error && error.code === 'EADDRINUSE') {
    const existing = await probeExistingBridge();
    if (existing.ok) {
      console.log(`wa-bridge already running on port ${port}`);
      process.exit(0);
      return;
    }

    console.error(`port ${port} is already in use by another process`);
    process.exit(1);
    return;
  }

  throw error;
});

process.on('SIGINT', () => scheduleShutdown('SIGINT'));
process.on('SIGTERM', () => scheduleShutdown('SIGTERM'));

const host = process.env.WA_BRIDGE_HOST || '127.0.0.1';
server.listen(port, host, () => {
  console.log(`wa-bridge listening on ${host}:${port}`);
});
