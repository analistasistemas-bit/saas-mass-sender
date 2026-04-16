const { execFile } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { promisify } = require('node:util');

const execFileAsync = promisify(execFile);

function isBrowserAlreadyRunningError(error) {
  const message = String(error && error.message ? error.message : error || '');
  return (
    message.includes('The browser is already running for')
    || message.includes('The profile appears to be in use by another Chromium process')
  );
}

function extractProfileOwnerPid(error) {
  const message = String(error && error.message ? error.message : error || '');
  const match = message.match(/another Chromium process\s+\((\d+)\)/i);
  if (!match) return null;
  const value = Number(match[1]);
  return Number.isInteger(value) ? value : null;
}

function parsePgrepOutput(output, userDataDir) {
  const escapedDir = userDataDir.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const pattern = new RegExp(`--user-data-dir=(["'])?${escapedDir}(?:\\1)(?:\\s|$)`);
  return String(output || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const match = line.match(/^(\d+)\s+(.*)$/);
      if (!match) return null;
      const pid = Number(match[1]);
      const command = match[2];
      return pattern.test(command) || command.includes(`--user-data-dir=${userDataDir}`) ? pid : null;
    })
    .filter((pid) => Number.isInteger(pid));
}

async function findSessionChromePids(userDataDir, runner = execFileAsync) {
  const candidates = [
    'Google Chrome for Testing',
    'Google Chrome',
    'Chromium',
    'HeadlessChrome',
    'chrome',
  ];
  const found = new Set();

  for (const candidate of candidates) {
    try {
      const { stdout } = await runner('pgrep', ['-af', candidate]);
      for (const pid of parsePgrepOutput(stdout, userDataDir)) {
        found.add(pid);
      }
    } catch (error) {
      const stdout = error && error.stdout ? error.stdout : '';
      for (const pid of parsePgrepOutput(stdout, userDataDir)) {
        found.add(pid);
      }
    }
  }

  return Array.from(found);
}

async function killPid(pid, signal, runner = execFileAsync) {
  try {
    await runner('kill', [`-${signal}`, String(pid)]);
    return true;
  } catch (_error) {
    return false;
  }
}

async function sleep(ms) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function releaseSessionBrowserLock(userDataDir, options = {}) {
  const runner = options.runner || execFileAsync;
  const fallbackPid = Number.isInteger(options.errorPid) ? options.errorPid : null;
  const discoveredPids = await findSessionChromePids(userDataDir, runner);
  const pids = Array.from(new Set([...(fallbackPid ? [fallbackPid] : []), ...discoveredPids]));
  const removedLockFiles = clearChromiumLockFiles(userDataDir);
  if (pids.length === 0) {
    return { killed: [], remaining: [], removedLockFiles };
  }

  for (const pid of pids) {
    await killPid(pid, 'TERM', runner);
  }

  await sleep(options.termGraceMs || 750);

  let remaining = await findSessionChromePids(userDataDir, runner);
  for (const pid of remaining) {
    await killPid(pid, 'KILL', runner);
  }

  await sleep(options.killGraceMs || 250);
  remaining = await findSessionChromePids(userDataDir, runner);

  return { killed: pids, remaining, removedLockFiles };
}

function clearChromiumLockFiles(userDataDir) {
  const lockFiles = ['SingletonLock', 'SingletonCookie', 'SingletonSocket'];
  const removed = [];
  for (const name of lockFiles) {
    const target = path.join(userDataDir, name);
    try {
      fs.lstatSync(target);
      fs.rmSync(target, { force: true });
      removed.push(name);
    } catch (_error) {
      // best effort cleanup
    }
  }
  return removed;
}

module.exports = {
  isBrowserAlreadyRunningError,
  extractProfileOwnerPid,
  parsePgrepOutput,
  findSessionChromePids,
  releaseSessionBrowserLock,
  clearChromiumLockFiles,
};
