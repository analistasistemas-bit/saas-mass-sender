const path = require('node:path');

const MAX_MEDIA_BYTES = 10 * 1024 * 1024;
const MAX_CAPTION_LENGTH = 1024;
const JSON_BODY_LIMIT = '16mb';

const ALLOWED_MIMETYPES = [
  'application/pdf',
  'image/jpeg',
  'image/png',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
];

const ALLOWED_MIMETYPE_SET = new Set(ALLOWED_MIMETYPES);

function reject(message, statusCode) {
  const error = new Error(message);
  error.statusCode = statusCode;
  return error;
}

function normalizeMimetype(value) {
  const raw = String(value || '').split(';')[0].trim().toLowerCase();
  if (raw === 'image/jpg' || raw === 'image/pjpeg') {
    return 'image/jpeg';
  }
  return raw;
}

function normalizeBase64(value) {
  let raw = String(value || '').trim();
  let declaredMime = '';
  const dataUrl = raw.match(/^data:([^;,]+);base64,([\s\S]+)$/i);
  if (dataUrl) {
    declaredMime = normalizeMimetype(dataUrl[1]);
    raw = dataUrl[2];
  }
  raw = raw.replace(/\s+/g, '');
  if (!raw || raw.length % 4 !== 0 || !/^[A-Za-z0-9+/]+={0,2}$/.test(raw)) {
    throw reject('media data must be base64', 400);
  }
  return { data: raw, declaredMime };
}

function sanitizeFilename(filename) {
  const base = path.basename(String(filename || '').replace(/\\/g, '/')).trim();
  if (!base || base === '.' || base === '..') {
    throw reject('filename is required', 400);
  }
  if (/[\u0000-\u001f\u007f]/.test(base) || base.includes('/') || base.includes('\\')) {
    throw reject('invalid filename', 400);
  }
  if (base.length > 180) {
    throw reject('filename is too long', 400);
  }
  return base;
}

function assertMagic(mimetype, buffer) {
  const ok =
    (mimetype === 'application/pdf' && buffer.subarray(0, 5).equals(Buffer.from('%PDF-'))) ||
    (mimetype === 'image/jpeg' && buffer.subarray(0, 3).equals(Buffer.from([0xff, 0xd8, 0xff]))) ||
    (mimetype === 'image/png' && buffer.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) ||
    (mimetype === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' &&
      buffer.subarray(0, 4).equals(Buffer.from([0x50, 0x4b, 0x03, 0x04])));
  if (!ok) {
    throw reject('file content does not match mimetype', 400);
  }
}

function prepareSendMedia(body) {
  const source = body && typeof body === 'object' ? body : {};
  const phone = String(source.phone || '').replace(/\D/g, '');
  const caption = String(source.caption || '').trim();
  if (!phone) {
    throw reject('phone is required', 400);
  }
  if (caption.length > MAX_CAPTION_LENGTH) {
    throw reject('caption is too long', 400);
  }

  const decoded = normalizeBase64(source.data);
  const mimetype = normalizeMimetype(source.mimetype) || decoded.declaredMime;
  if (!ALLOWED_MIMETYPE_SET.has(mimetype)) {
    throw reject('unsupported mimetype', 400);
  }

  const filename = sanitizeFilename(source.filename);
  const buffer = Buffer.from(decoded.data, 'base64');
  if (buffer.length === 0) {
    throw reject('media data is empty', 400);
  }
  if (buffer.length > MAX_MEDIA_BYTES) {
    throw reject('media exceeds 10MB limit', 413);
  }
  assertMagic(mimetype, buffer);

  return {
    phone,
    caption,
    filename,
    mimetype,
    data: decoded.data,
    filesize: buffer.length,
  };
}

const DOCUMENT_MIMETYPES = new Set([
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
]);

function buildSendMediaOptions(prepared) {
  const source = prepared && typeof prepared === 'object' ? prepared : {};
  const options = {};
  if (source.caption) {
    options.caption = source.caption;
  }
  if (DOCUMENT_MIMETYPES.has(source.mimetype)) {
    options.sendMediaAsDocument = true;
  }
  return options;
}

module.exports = {
  ALLOWED_MIMETYPES,
  JSON_BODY_LIMIT,
  MAX_CAPTION_LENGTH,
  MAX_MEDIA_BYTES,
  buildSendMediaOptions,
  prepareSendMedia,
};
