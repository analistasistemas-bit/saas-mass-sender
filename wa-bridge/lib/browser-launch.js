// Puppeteer 24 treats `headless: true` as the current headless browser.
// The older `headless: 'new'` alias is not a valid LaunchOptions value here.

const DISTRO_CHROMIUM = /(?:^|\/)(?:chromium|chromium-browser)(?:$|\s)/;

function resolveHeadless(envValue) {
  return String(envValue == null ? 'true' : envValue).trim().toLowerCase() !== 'false';
}

function resolveExecutablePath(envOverride, bundledExecutable) {
  const override = String(envOverride || '').trim();
  if (override) {
    return { executablePath: override, browserSource: 'WA_EXECUTABLE_PATH' };
  }
  const bundled = String(bundledExecutable || '').trim();
  if (!bundled) {
    throw new Error(
      'Puppeteer Chrome is not installed. Leave WA_EXECUTABLE_PATH unset and install whatsapp-web.js dependencies so puppeteer.executablePath() resolves.'
    );
  }
  return { executablePath: bundled, browserSource: 'puppeteer-bundled' };
}

function isDistroChromiumPath(executablePath) {
  return DISTRO_CHROMIUM.test(String(executablePath || ''));
}

function buildPuppeteerLaunchOptions({ headlessEnv, executableOverride, bundledExecutable } = {}) {
  const browser = resolveExecutablePath(executableOverride, bundledExecutable);
  return {
    headless: resolveHeadless(headlessEnv),
    executablePath: browser.executablePath,
    browserSource: browser.browserSource,
    distroChromium: isDistroChromiumPath(browser.executablePath),
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
    ],
  };
}

module.exports = {
  buildPuppeteerLaunchOptions,
  isDistroChromiumPath,
  resolveExecutablePath,
  resolveHeadless,
};
