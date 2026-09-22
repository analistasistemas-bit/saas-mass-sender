const fs = require('node:fs');
const Module = require('node:module');

const PATCH_MARKER = 'delete message.__x_id;';

// Anchor is the sendMessage() object in whatsapp-web.js 1.34.7
// src/util/Injected/Utils.js. mediaOptions is a MediaData model; spreading
// it copies __x_id: undefined onto the outgoing Msg and WA Web's getter throws
// "Data passed to getter must include an id property".
const ANCHOR = [
  '        };',
  '',
  "        // Bot's won't reply if canonicalUrl is set (linking)",
].join('\n');

const INSERTION = [
  '        };',
  '',
  '        // MediaData.__x_id collides with Msg.id on WhatsApp Web 2.3000.10477+.',
  '        // https://github.com/wwebjs/whatsapp-web.js/issues/201922',
  '        delete message.__x_id;',
  '',
  "        // Bot's won't reply if canonicalUrl is set (linking)",
].join('\n');

function patchSendMessageSource(source) {
  const text = String(source);
  if (text.includes(PATCH_MARKER)) {
    return text;
  }
  if (!text.includes(ANCHOR)) {
    const error = new Error(
      'whatsapp-web.js media send patch anchor missing in Injected/Utils.js. Pinned 1.34.7 is required for this workaround.',
    );
    error.code = 'WWEBJS_MEDIA_PATCH_MISMATCH';
    throw error;
  }
  return text.replace(ANCHOR, INSERTION);
}

function utilsFilePath() {
  return require.resolve('whatsapp-web.js/src/util/Injected/Utils.js');
}

let installed = false;

function installWhatsappWebJsMediaSendPatch() {
  const target = utilsFilePath();
  const cached = require.cache[target];
  if (cached && cached.exports && typeof cached.exports.LoadUtils === 'function') {
    const body = Function.prototype.toString.call(cached.exports.LoadUtils);
    if (!body.includes(PATCH_MARKER)) {
      const error = new Error('whatsapp-web.js was loaded before the media send patch');
      error.code = 'WWEBJS_MEDIA_PATCH_LATE';
      throw error;
    }
    return;
  }

  const patched = patchSendMessageSource(fs.readFileSync(target, 'utf8'));
  if (!patched.includes(PATCH_MARKER)) {
    const error = new Error('whatsapp-web.js media send patch did not apply');
    error.code = 'WWEBJS_MEDIA_PATCH_MISMATCH';
    throw error;
  }

  if (installed) {
    return;
  }

  const loadJs = Module._extensions['.js'];
  Module._extensions['.js'] = function mediaSendPatchLoader(mod, filename) {
    if (filename === target) {
      const current = fs.readFileSync(filename, 'utf8');
      mod._compile(patchSendMessageSource(current), filename);
      return;
    }
    return loadJs.call(this, mod, filename);
  };
  installed = true;
}

module.exports = {
  PATCH_MARKER,
  installWhatsappWebJsMediaSendPatch,
  patchSendMessageSource,
  utilsFilePath,
};
