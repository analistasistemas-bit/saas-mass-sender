const fs = require('node:fs');

function loadEnvFile(envPath) {
  let content;
  try {
    content = fs.readFileSync(envPath, 'utf8');
  } catch (error) {
    if (error && error.code === 'ENOENT') {
      return;
    }
    throw error;
  }

  for (const line of content.split(/\r?\n/)) {
    const entry = line.trim();
    if (!entry || entry.startsWith('#') || !entry.includes('=')) {
      continue;
    }
    const separator = entry.indexOf('=');
    const key = entry.slice(0, separator).trim();
    const value = entry.slice(separator + 1).trim();
    if (!key || process.env[key] !== undefined) {
      continue;
    }
    process.env[key] = value;
  }
}

module.exports = {
  loadEnvFile,
};
