const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const {
  PATCH_MARKER,
  installWhatsappWebJsMediaSendPatch,
  patchSendMessageSource,
  utilsFilePath,
} = require('../lib/patch-wwebjs-media-send');

const FIXTURE = [
  '            ...mediaOptions,',
  '            ...(mediaOptions.toJSON ? mediaOptions.toJSON() : {}),',
  '            ...extraOptions,',
  '        };',
  '',
  "        // Bot's won't reply if canonicalUrl is set (linking)",
  '        if (botOptions) {',
  '            delete message.canonicalUrl;',
  '        }',
].join('\n');

test('patchSendMessageSource drops MediaData __x_id after the message object is built', () => {
  const patched = patchSendMessageSource(FIXTURE);

  assert.match(patched, /\.\.\.mediaOptions,/);
  assert.match(patched, /\.\.\.\(mediaOptions\.toJSON \? mediaOptions\.toJSON\(\) : \{\}\),/);
  const spreadAt = patched.indexOf('...mediaOptions,');
  const markerAt = patched.indexOf(PATCH_MARKER);
  const botAt = patched.indexOf('if (botOptions)');
  assert.ok(spreadAt !== -1 && spreadAt < markerAt && markerAt < botAt);
  assert.equal(patchSendMessageSource(patched), patched);
});

test('patchSendMessageSource rejects an unexpected library body', () => {
  assert.throws(() => patchSendMessageSource('window.WWebJS.sendMessage = async () => {};'), {
    code: 'WWEBJS_MEDIA_PATCH_MISMATCH',
  });
});

test('unpatched media spread keeps __x_id undefined beside the real MsgKey', () => {
  const newMsgKey = { id: '3EB0', _serialized: 'true_5581996459595@c.us_3EB0' };
  const mediaOptions = {
    mimetype: 'application/pdf',
    filename: 'nota.pdf',
    clientUrl: 'https://mmg.whatsapp.net/upload',
    __x_id: undefined,
    toJSON() {
      return {
        mimetype: this.mimetype,
        filename: this.filename,
        clientUrl: this.clientUrl,
      };
    },
  };

  const unpatched = {
    id: newMsgKey,
    type: 'chat',
    ...mediaOptions,
    ...(mediaOptions.toJSON ? mediaOptions.toJSON() : {}),
  };
  assert.equal(Object.hasOwn(unpatched, '__x_id'), true);
  assert.equal(unpatched.__x_id, undefined);
  assert.equal(unpatched.id, newMsgKey);

  const patched = { ...unpatched };
  delete patched.__x_id;
  assert.equal(Object.hasOwn(patched, '__x_id'), false);
  assert.equal(patched.id, newMsgKey);
  assert.equal(patched.clientUrl, mediaOptions.clientUrl);
  assert.equal(patched.filename, 'nota.pdf');
});

test('installed whatsapp-web.js 1.34.7 LoadUtils receives the media id patch', () => {
  const utilsPath = utilsFilePath();
  const pkg = require('whatsapp-web.js/package.json');
  assert.equal(pkg.version, '1.34.7');

  const original = fs.readFileSync(utilsPath, 'utf8');
  assert.equal(original.includes(PATCH_MARKER), false);
  const patched = patchSendMessageSource(original);
  assert.notEqual(patched, original);
  assert.equal(patched.includes(PATCH_MARKER), true);
  assert.equal(patchSendMessageSource(patched), patched);

  delete require.cache[utilsPath];
  installWhatsappWebJsMediaSendPatch();
  const loaded = require('whatsapp-web.js/src/util/Injected/Utils.js');
  assert.match(Function.prototype.toString.call(loaded.LoadUtils), /delete message\.__x_id;/);
  assert.equal(fs.readFileSync(utilsPath, 'utf8'), original);
});
