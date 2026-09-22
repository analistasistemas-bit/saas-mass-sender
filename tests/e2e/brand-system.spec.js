const { test, expect } = require('@playwright/test');

test('aplica a hierarquia Daludi e Mass Sender no login e dashboard', async ({ page }) => {
  await page.goto('/login');
  await expect(page.getByTestId('daludi-masthead')).toBeVisible();
  await expect(page.getByAltText('Daludi')).toHaveAttribute('src', '/static/brand/png/daludi-logo-digital.png');
  await expect(page.getByTestId('mass-sender-product-mark').getByAltText('Mass Sender')).toHaveAttribute(
    'src',
    '/static/brand/mass-sender-cofre-horizontal.svg',
  );

  await page.locator('input[name="password"]').fill('admin123');
  await page.getByRole('button', { name: 'Entrar' }).click();
  await expect(page.getByTestId('daludi-masthead')).toBeVisible();
  await expect(page.getByTestId('mass-sender-product-mark')).toBeVisible();

  await page.setViewportSize({ width: 320, height: 800 });
  await expect(page.getByTestId('daludi-masthead')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.locator('input[name="name"]').fill('Campanha de marca');
  await page.getByRole('button', { name: 'Criar campanha' }).click();
  await expect(page.locator('[data-testid="primary-action"]')).toBeVisible();
});
