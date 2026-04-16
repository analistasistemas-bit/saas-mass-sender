const test = require('node:test');
const assert = require('node:assert/strict');

const {
  shouldForwardInboundMessage,
  buildInboundPayload,
  publishInboundWebhook,
} = require('../lib/inbound-webhook');

test('shouldForwardInboundMessage ignores fromMe messages', () => {
  assert.equal(shouldForwardInboundMessage({ fromMe: true, body: 'oi' }), false);
});

test('shouldForwardInboundMessage ignores group messages', () => {
  assert.equal(shouldForwardInboundMessage({ from: '123@g.us', body: 'oi' }), false);
});

test('shouldForwardInboundMessage ignores empty messages', () => {
  assert.equal(shouldForwardInboundMessage({ from: '5511999999999@c.us', body: '   ' }), false);
});

test('buildInboundPayload normalizes message shape', () => {
  const payload = buildInboundPayload({
    id: { _serialized: 'wamid.1' },
    from: '5511999999999@c.us',
    to: '5581888888888@c.us',
    body: 'Olá',
    type: 'chat',
    fromMe: false,
    timestamp: 1711720000,
    _data: { notifyName: 'Maria' },
  });

  assert.equal(payload.wa_message_id, 'wamid.1');
  assert.equal(payload.from_phone, '5511999999999');
  assert.equal(payload.to_phone, '5581888888888');
  assert.equal(payload.text, 'Olá');
  assert.equal(payload.from_me, false);
  assert.equal(payload.push_name, 'Maria');
});

test('publishInboundWebhook sends authenticated payload', async () => {
  const calls = [];
  const fakeFetch = async (url, options) => {
    calls.push({ url, options });
    return { ok: true, status: 200, json: async () => ({ ok: true }) };
  };

  const result = await publishInboundWebhook(
    {
      wa_message_id: 'wamid.1',
      from_phone: '5511999999999',
      to_phone: '5581888888888',
      text: 'Olá',
      timestamp: '2026-03-29T15:00:00Z',
      push_name: 'Maria',
      message_type: 'chat',
      from_me: false,
      raw_excerpt: '{"text":"Olá"}',
    },
    {
      backendUrl: 'http://127.0.0.1:8000/webhooks/whatsapp/inbound',
      token: 'secret-token',
      fetchImpl: fakeFetch,
    },
  );

  assert.equal(result.ok, true);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'http://127.0.0.1:8000/webhooks/whatsapp/inbound');
  assert.equal(calls[0].options.method, 'POST');
  assert.equal(calls[0].options.headers['x-inbound-token'], 'secret-token');
});
