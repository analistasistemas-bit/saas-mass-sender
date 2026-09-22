function phoneFromJid(value) {
  return String(value || '').split('@')[0].replace(/\D/g, '');
}

function messageId(message) {
  const id = message && message.id;
  if (id && typeof id === 'object') {
    return String(id._serialized || id.id || '');
  }
  return String(id || '');
}

function shouldForwardInboundMessage(message) {
  if (!message || message.fromMe) {
    return false;
  }
  if (String(message.from || '').includes('@g.us')) {
    return false;
  }
  return Boolean(String(message.body || '').trim());
}

function buildInboundPayload(message) {
  const text = String((message && message.body) || '');
  const notifyName = (message && message._data && message._data.notifyName) || (message && message.notifyName) || '';
  let timestamp = '';
  if (message && message.timestamp != null && message.timestamp !== '') {
    const numeric = Number(message.timestamp);
    const raw = String(message.timestamp);
    if (Number.isFinite(numeric) && !raw.includes('-') && !raw.includes('T')) {
      const milliseconds = numeric < 1e12 ? numeric * 1000 : numeric;
      timestamp = new Date(milliseconds).toISOString();
    } else {
      timestamp = raw;
    }
  }

  return {
    wa_message_id: messageId(message),
    from_phone: phoneFromJid(message && message.from),
    to_phone: phoneFromJid(message && message.to),
    text,
    timestamp,
    push_name: String(notifyName || ''),
    message_type: String((message && message.type) || 'chat'),
    from_me: Boolean(message && message.fromMe),
    raw_excerpt: JSON.stringify({ text }).slice(0, 500),
  };
}

async function publishInboundWebhook(payload, options = {}) {
  const backendUrl = String(options.backendUrl || '').trim();
  if (!backendUrl) {
    return { ok: false, status: 0 };
  }

  const fetchImpl = options.fetchImpl || fetch;
  const response = await fetchImpl(backendUrl, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'x-inbound-token': String(options.token || ''),
    },
    body: JSON.stringify(payload),
  });

  return {
    ok: Boolean(response && response.ok),
    status: Number(response && response.status) || 0,
  };
}

module.exports = {
  shouldForwardInboundMessage,
  buildInboundPayload,
  publishInboundWebhook,
};
