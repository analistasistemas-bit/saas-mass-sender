const test = require('node:test');
const assert = require('node:assert/strict');

const {
  buildPuppeteerLaunchOptions,
  isDistroChromiumPath,
  resolveHeadless,
} = require('../lib/browser-launch');

const BUNDLED = '/opt/puppeteer/chrome-linux64/chrome';

test('default launch uses bundled Chrome and modern headless', () => {
  const launch = buildPuppeteerLaunchOptions({
    bundledExecutable: BUNDLED,
  });

  assert.equal(launch.headless, true);
  assert.equal(launch.executablePath, BUNDLED);
  assert.equal(launch.browserSource, 'puppeteer-bundled');
  assert.equal(launch.distroChromium, false);
  assert.equal(launch.args.includes('--single-process'), false);
  assert.equal(launch.args.includes('--no-zygote'), false);
  assert.equal(launch.args.some((arg) => arg.includes('max-old-space-size')), false);
  assert.equal(launch.args.includes('--no-sandbox'), true);
});

test('WA_HEADLESS=false launches a headed browser', () => {
  assert.equal(resolveHeadless('false'), false);
  assert.equal(resolveHeadless('FALSE'), false);
  assert.equal(resolveHeadless('true'), true);
  assert.equal(resolveHeadless(undefined), true);

  const launch = buildPuppeteerLaunchOptions({
    headlessEnv: 'false',
    bundledExecutable: BUNDLED,
  });
  assert.equal(launch.headless, false);
});

test('WA_EXECUTABLE_PATH overrides bundled Chrome and flags distro Chromium', () => {
  const launch = buildPuppeteerLaunchOptions({
    executableOverride: '/usr/bin/chromium',
    bundledExecutable: BUNDLED,
  });

  assert.equal(launch.executablePath, '/usr/bin/chromium');
  assert.equal(launch.browserSource, 'WA_EXECUTABLE_PATH');
  assert.equal(launch.distroChromium, true);
  assert.equal(isDistroChromiumPath('/usr/bin/chromium-browser'), true);
  assert.equal(isDistroChromiumPath(BUNDLED), false);
});

test('empty override falls back to bundled Chrome', () => {
  const launch = buildPuppeteerLaunchOptions({
    executableOverride: '   ',
    bundledExecutable: BUNDLED,
  });
  assert.equal(launch.executablePath, BUNDLED);
  assert.equal(launch.browserSource, 'puppeteer-bundled');
});

test('missing bundled Chrome fails closed when no override is set', () => {
  assert.throws(
    () => buildPuppeteerLaunchOptions({ bundledExecutable: '' }),
    /Puppeteer Chrome is not installed/,
  );
});
