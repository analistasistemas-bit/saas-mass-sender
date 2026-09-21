const test = require('node:test');
const assert = require('node:assert/strict');

const { JSON_BODY_LIMIT, MAX_MEDIA_BYTES, prepareSendMedia } = require('../lib/send-media');

function b64(bytes) {
  return Buffer.from(bytes).toString('base64');
}

test('prepareSendMedia accepts a pdf payload', () => {
  const prepared = prepareSendMedia({
    phone: '+55 (81) 99999-9999',
    caption: 'boleto',
    filename: 'docs/boleto.pdf',
    mimetype: 'application/pdf',
    data: b64(Buffer.from('%PDF-1.4 sample')),
  });

  assert.equal(prepared.phone, '5581999999999');
  assert.equal(prepared.caption, 'boleto');
  assert.equal(prepared.filename, 'boleto.pdf');
  assert.equal(prepared.mimetype, 'application/pdf');
  assert.equal(prepared.filesize, Buffer.from('%PDF-1.4 sample').length);
});

test('prepareSendMedia strips a data URL and accepts jpeg alias', () => {
  const raw = Buffer.from([0xff, 0xd8, 0xff, 0xd9]);
  const prepared = prepareSendMedia({
    phone: '5581888888888',
    filename: 'foto.jpg',
    mimetype: 'image/jpg',
    data: `data:image/jpeg;base64,${b64(raw)}`,
  });

  assert.equal(prepared.mimetype, 'image/jpeg');
  assert.equal(prepared.caption, '');
  assert.equal(prepared.data, b64(raw));
});

test('prepareSendMedia accepts png and docx signatures', () => {
  const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00]);
  const docx = Buffer.from([0x50, 0x4b, 0x03, 0x04, 0x14]);

  assert.equal(prepareSendMedia({ phone: '1', filename: 'a.png', mimetype: 'image/png', data: b64(png) }).mimetype, 'image/png');
  assert.equal(
    prepareSendMedia({
      phone: '1',
      filename: 'a.docx',
      mimetype: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      data: b64(docx),
    }).mimetype,
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  );
});

test('prepareSendMedia rejects missing fields, bad type, mismatched bytes, and oversize files', () => {
  assert.throws(() => prepareSendMedia({ filename: 'a.pdf', mimetype: 'application/pdf', data: b64('%PDF-') }), {
    message: 'phone is required',
    statusCode: 400,
  });
  assert.throws(() => prepareSendMedia({ phone: '1', mimetype: 'application/pdf', data: b64('%PDF-') }), {
    message: 'filename is required',
  });
  assert.throws(() => prepareSendMedia({ phone: '1', filename: 'a.exe', mimetype: 'application/octet-stream', data: b64('hello') }), {
    message: 'unsupported mimetype',
  });
  assert.throws(() => prepareSendMedia({ phone: '1', filename: 'a.pdf', mimetype: 'application/pdf', data: b64('not-a-pdf') }), {
    message: 'file content does not match mimetype',
  });

  const tooBig = Buffer.concat([Buffer.from('%PDF-'), Buffer.alloc(MAX_MEDIA_BYTES)]);
  assert.throws(() => prepareSendMedia({ phone: '1', filename: 'a.pdf', mimetype: 'application/pdf', data: b64(tooBig) }), {
    message: 'media exceeds 10MB limit',
    statusCode: 413,
  });
});

test('json body limit fits a 10MB file after base64', () => {
  assert.equal(JSON_BODY_LIMIT, '16mb');
  const base64Bytes = Math.ceil(MAX_MEDIA_BYTES / 3) * 4;
  assert.ok(base64Bytes < 16 * 1024 * 1024);
});
