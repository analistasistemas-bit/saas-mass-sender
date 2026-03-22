const { test, expect } = require('@playwright/test');
const path = require('path');

const QR_BASE64 =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO3Z8m8AAAAASUVORK5CYII=';

test('faixa principal mostra processamento e toast final nas fases operacionais', async ({ page }) => {
  let sessionState = {
    connected: true,
    state: 'connected',
    phone: '+55 81 99999-9999',
    hasQr: false,
    lastError: null,
    history: [],
  };

  let statsState = {
    campaign_id: 1,
    status: 'draft',
    sent: 0,
    failed: 0,
    pending: 0,
    valid: 0,
    invalid: 0,
    total: 0,
    test_completed_at: null,
    started_at: null,
    finished_at: null,
    updated_at: '2026-03-18T12:00:00+00:00',
    sent_today: 0,
    daily_limit: 0,
    pause_reason: null,
    speed_profile: 'conservative',
    send_delay_min_seconds: 5,
    send_delay_max_seconds: 10,
    batch_pause_min_seconds: 5,
    batch_pause_max_seconds: 10,
    batch_size_initial: 10,
    batch_size_max: 25,
    batch_growth_step: 2,
    batch_growth_streak_required: 3,
    batch_shrink_step: 2,
    batch_shrink_error_streak_required: 2,
    batch_size_floor: 5,
    send_window_start: '08:00',
    send_window_end: '20:00',
    runtime_profile: {
      selected_profile: 'conservative',
      effective_profile: 'conservative',
      batch_size_current: 10,
      batch_pause_min_seconds: 5,
      batch_pause_max_seconds: 10,
      profile_source: 'preset',
    },
    performance: {
      observed_contacts_per_minute: 0,
      observed_seconds_per_contact: 0,
      measurement_window_seconds: 600,
      measurement_basis: 'warming_up',
      last_activity_at: null,
      sample_size: 0,
      warming_up: true,
    },
    estimates: {
      remaining_seconds_observed: 0,
      remaining_seconds_conservative: 0,
      configured_seconds_per_contact_min: 15,
      configured_seconds_per_contact_max: 45,
      configured_batch_pause_min: 25,
      configured_batch_pause_max: 40,
      label_speed: 'Aquecendo medicao',
      label_eta: 'Calculando com base na execucao real',
      label_configured_pace: 'Config.: 15-45s por envio + pausas operacionais',
    },
  };

  let overviewState = {
    results: {
      headline: 'Resultados parciais',
      summary: 'Os principais indicadores aparecem aqui quando houver execucao suficiente.',
      processed: 0,
      success_rate: 0,
      failure_rate: 0,
      coverage_rate: 0,
      duration_seconds: 0,
      distribution: { sent: 0, failed: 0, pending: 0, invalid: 0, valid: 0, total: 0 },
      top_failures: [],
      started_at: null,
      finished_at: null,
    },
    activity: {
      total_events: 0,
      summary_cards: [
        { key: 'state', label: 'Mudancas de estado', count: 0, tone: 'info' },
        { key: 'success', label: 'Entregas confirmadas', count: 0, tone: 'success' },
        { key: 'retry', label: 'Novas tentativas', count: 0, tone: 'warn' },
        { key: 'failure', label: 'Falhas tecnicas', count: 0, tone: 'error' },
      ],
      milestones: [],
      incidents: [],
    },
  };

  let contactsItems = [];

  await page.route('**/bridge/session', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, session: sessionState }),
    });
  });

  await page.route('**/campaigns/*/stats', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(statsState),
    });
  });

  await page.route('**/campaigns/*/overview', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(overviewState),
    });
  });

  await page.route('**/campaigns/*/contacts?**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: contactsItems,
        pagination: { page: 1, total_pages: 1, total: contactsItems.length, page_size: 25 },
        status_filter: '',
      }),
    });
  });

  await page.route('**/campaigns/*/settings', async (route) => {
    const body = route.request().postData() || '';
    const params = new URLSearchParams(body);
    await page.waitForTimeout(250);
    statsState = {
      ...statsState,
      send_delay_min_seconds: 18,
      send_delay_max_seconds: 48,
      send_window_start: params.get('send_window_start') || statsState.send_window_start,
      send_window_end: params.get('send_window_end') || statsState.send_window_end,
      updated_at: '2026-03-18T12:00:15+00:00',
    };
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, message: 'Configuracoes operacionais salvas.' }),
    });
  });

  await page.route('**/campaigns/*/template', async (route) => {
    await page.waitForTimeout(250);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, message: 'Mensagem salva.' }),
    });
  });

  await page.route('**/campaigns/*/contacts/upload', async (route) => {
    await page.waitForTimeout(250);
    contactsItems = [
      {
        id: 901,
        name: 'Cliente E2E',
        phone_raw: '11999998888',
        phone_e164: '+5511999998888',
        email: 'cliente-e2e@teste.com',
        status: 'pending',
        error_message: '',
      },
    ];
    statsState = {
      ...statsState,
      status: 'ready',
      valid: 1,
      total: 1,
      pending: 1,
      updated_at: '2026-03-18T12:01:00+00:00',
    };
    overviewState = {
      ...overviewState,
      results: {
        ...overviewState.results,
        distribution: { sent: 0, failed: 0, pending: 1, invalid: 0, valid: 1, total: 1 },
      },
    };
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        summary: { total: 1, valid: 1, invalid: 0, inserted: 1, replaced_previous_csv_contacts: 0 },
      }),
    });
  });

  await page.goto('/login');
  await page.getByPlaceholder('Senha').fill('admin123');
  await page.getByRole('button', { name: 'Entrar' }).click();

  await page.locator('input[name="name"]').fill('Campanha Feedback');
  await page.getByRole('button', { name: 'Criar campanha' }).click();

  await expect(page.getByRole('heading', { name: 'Campanha Feedback' })).toBeVisible();

  await page.locator('#settings-form input[name="send_delay_min_seconds"]').fill('18');
  await page.locator('#settings-form input[name="send_delay_max_seconds"]').fill('48');
  const saveSettingsPromise = page.getByRole('button', { name: 'Salvar configuracoes' }).click();
  await expect(page.locator('[data-testid="status-narrative"]')).toContainText('Processando salvamento das configuracoes operacionais...');
  await saveSettingsPromise;
  await expect(page.getByText('Configuracoes operacionais salvas.')).toBeVisible();

  await page.locator('textarea[name="message_template"]').fill('Oi, {{nome}}! Mensagem E2E');
  const saveTemplatePromise = page.getByRole('button', { name: 'Salvar mensagem' }).click();
  await expect(page.locator('[data-testid="status-narrative"]')).toContainText('Processando salvamento da mensagem da campanha...');
  await saveTemplatePromise;
  await expect(page.getByText('Mensagem salva.')).toBeVisible();

  await page.setInputFiles('input[name="csv_file"]', path.resolve(__dirname, '../fixtures/contatos_e2e.csv'));
  const uploadPromise = page.getByRole('button', { name: 'Enviar CSV' }).click();
  await uploadPromise;
  await expect(page.getByText('Upload concluido com sucesso.')).toBeVisible();
});
