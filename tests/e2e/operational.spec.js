const { test, expect } = require('@playwright/test');
const path = require('path');

const QR_BASE64 =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO3Z8m8AAAAASUVORK5CYII=';

test('fluxo operacional guiado da home ate a conclusao', async ({ page }) => {
  let sessionState = {
    connected: false,
    state: 'qr_ready',
    phone: null,
    hasQr: true,
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
      configured_seconds_per_contact_min: 5,
      configured_seconds_per_contact_max: 10,
      configured_batch_pause_min: 5,
      configured_batch_pause_max: 10,
      label_speed: 'Aquecendo medicao',
      label_eta: 'Calculando com base na execucao real',
      label_configured_pace: 'Config.: 5-10s por envio + pausas operacionais',
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
      distribution: {
        sent: 0,
        failed: 0,
        pending: 0,
        invalid: 0,
        valid: 0,
        total: 0,
      },
      top_failures: [],
      started_at: null,
      finished_at: null,
      reprocessing: null,
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
  let deleteContactCalled = false;
  let deleteImportedCalled = false;
  let deleteCampaignCalled = false;
  let failedReprocessingCalled = false;
  let currentContactsPage = 1;
  let currentPerPage = 10;
  let currentStatusFilter = '';
  let overviewFailureCountdown = 0;
  let contactsItems = Array.from({ length: 26 }, (_, index) => ({
    id: index + 1,
    name: `Cliente ${index + 1}`,
    phone_raw: `819999999${String(index + 1).padStart(2, '0')}`,
    phone_e164: `+55819999999${String(index + 1).padStart(2, '0')}`,
    email: `cliente${index + 1}@example.com`,
    status: 'failed',
    error_message: '',
  }));

  await page.route('**/bridge/session', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, session: sessionState }),
    });
  });

  await page.route('**/bridge/qr', async (route) => {
    sessionState = {
      ...sessionState,
      connected: true,
      state: 'connected',
      phone: '+55 81 99999-9999',
      hasQr: false,
    };
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        qr: {
          ok: true,
          base64: QR_BASE64,
        },
      }),
    });
  });

  await page.route('**/bridge/reset', async (route) => {
    sessionState = {
      connected: false,
      state: 'qr_ready',
      phone: null,
      hasQr: true,
      lastError: null,
      history: [],
    };
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, result: { ok: true, message: 'session restarting' } }),
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
    if (overviewFailureCountdown > 0) {
      overviewFailureCountdown -= 1;
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ ok: false, message: 'overview temporarily unavailable' }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(overviewState),
    });
  });

  await page.route('**/campaigns/*/settings', async (route) => {
    const body = route.request().postData() || '';
    const params = new URLSearchParams(body);
    const minDelay = Number(params.get('send_delay_min_seconds') || '5');
    const maxDelay = Number(params.get('send_delay_max_seconds') || '10');
    const batchPauseMin = Number(params.get('batch_pause_min_seconds') || '5');
    const batchPauseMax = Number(params.get('batch_pause_max_seconds') || '10');
    const sendWindowStart = params.get('send_window_start') || '08:00';
    const sendWindowEnd = params.get('send_window_end') || '20:00';
    const speedProfile = params.get('speed_profile') || 'conservative';
    statsState = {
      ...statsState,
      speed_profile: speedProfile,
      send_delay_min_seconds: minDelay,
      send_delay_max_seconds: maxDelay,
      batch_pause_min_seconds: batchPauseMin,
      batch_pause_max_seconds: batchPauseMax,
      send_window_start: sendWindowStart,
      send_window_end: sendWindowEnd,
      daily_limit: Number(params.get('daily_limit') || '0'),
      runtime_profile: {
        ...statsState.runtime_profile,
        selected_profile: speedProfile,
        effective_profile: speedProfile,
        batch_pause_min_seconds: batchPauseMin,
        batch_pause_max_seconds: batchPauseMax,
        profile_source: speedProfile === 'custom' ? 'manual_override' : 'preset',
      },
      estimates: {
        ...statsState.estimates,
        configured_seconds_per_contact_min: minDelay,
        configured_seconds_per_contact_max: maxDelay,
        configured_batch_pause_min: batchPauseMin,
        configured_batch_pause_max: batchPauseMax,
        label_configured_pace: `Config.: ${minDelay}-${maxDelay}s por envio + pausas operacionais`,
      },
      updated_at: '2026-03-18T12:00:15+00:00',
    };
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        message: 'Configuracoes operacionais salvas.',
        settings: {
          speed_profile: speedProfile,
          send_delay_min_seconds: minDelay,
          send_delay_max_seconds: maxDelay,
          batch_pause_min_seconds: batchPauseMin,
          batch_pause_max_seconds: batchPauseMax,
          send_window_start: sendWindowStart,
          send_window_end: sendWindowEnd,
          daily_limit: statsState.daily_limit,
        },
      }),
    });
  });

  await page.route('**/campaigns/*/contacts/upload', async (route) => {
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
      ...contactsItems.filter((item) => item.id === 900),
    ];
    statsState = {
      ...statsState,
      status: 'ready',
      pending: 2,
      valid: 2,
      invalid: 0,
      total: 2,
      updated_at: '2026-03-18T12:01:00+00:00',
    };
    overviewState = {
      ...overviewState,
      results: {
        ...overviewState.results,
        headline: 'Resultados parciais',
        summary: 'Base pronta para a proxima etapa operacional.',
        coverage_rate: 0,
        distribution: { sent: 0, failed: 0, pending: 2, invalid: 0, valid: 2, total: 2 },
      },
    };
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        summary: {
          total: 1,
          valid: 1,
          invalid: 0,
          inserted: 1,
          duplicates_skipped: 0,
        },
      }),
    });
  });

  await page.route('**/campaigns/*/contacts/manual', async (route) => {
    const body = route.request().postData() || '';
    const params = new URLSearchParams(body);
    const phone = (params.get('phone') || '').trim();
    if (phone === '1234') {
      await route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({ ok: false, message: 'Formato inválido para Brasil (+55)' }),
      });
      return;
    }

    statsState = {
      ...statsState,
      status: 'ready',
      pending: 1,
      valid: 1,
      invalid: 0,
      total: 1,
      updated_at: '2026-03-18T12:00:30+00:00',
    };
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        contact: {
          id: 900,
          name: params.get('name') || 'Cliente Manual',
          phone_raw: phone,
          phone_e164: '+5581999999999',
          email: params.get('email') || '',
          status: 'pending',
        },
      }),
    });
  });

  await page.route(/\/campaigns\/\d+\/contacts(\?.*)?$/, async (route) => {
    const url = new URL(route.request().url());
    currentContactsPage = Number(url.searchParams.get('page') || '1');
    currentPerPage = Number(url.searchParams.get('per_page') || '10');
    currentStatusFilter = (url.searchParams.get('status') || '').trim();
    const filteredItems = currentStatusFilter ? contactsItems.filter((item) => item.status === currentStatusFilter) : contactsItems;
    const offset = (currentContactsPage - 1) * currentPerPage;
    const items = filteredItems.slice(offset, offset + currentPerPage);
    const totalPages = Math.max(1, Math.ceil(filteredItems.length / currentPerPage));
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items,
        pagination: {
          page: currentContactsPage,
          total_pages: totalPages,
          total: filteredItems.length,
          page_size: currentPerPage,
        },
        status_filter: currentStatusFilter,
      }),
    });
  });

  await page.route('**/campaigns/*/contacts/*/delete', async (route) => {
    deleteContactCalled = true;
    contactsItems = contactsItems.slice(1);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, message: 'Contato removido da campanha com sucesso.' }),
    });
  });

  await page.route('**/campaigns/*/contacts/delete-imported', async (route) => {
    deleteImportedCalled = true;
    contactsItems = [
      {
        id: 900,
        name: 'Cliente Manual',
        phone_raw: '+55 81999999999',
        phone_e164: '+5581999999999',
        email: 'manual@cliente.com',
        status: 'pending',
        error_message: '',
      },
    ];
    statsState = {
      ...statsState,
      pending: 1,
      valid: 1,
      invalid: 0,
      total: 1,
      updated_at: '2026-03-18T12:01:30+00:00',
    };
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, message: 'Contatos importados removidos com sucesso.', deleted_count: 25 }),
    });
  });

  await page.route('**/campaigns/*/delete', async (route) => {
    deleteCampaignCalled = true;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, message: 'Campanha excluida com sucesso.', redirect_url: '/' }),
    });
  });

  await page.route('**/campaigns/*/restart', async (route) => {
    const body = route.request().postData() || '';
    const params = new URLSearchParams(body);
    const mode = params.get('mode') || 'all';
    if (mode === 'failed') {
      failedReprocessingCalled = true;
      statsState = {
        ...statsState,
        status: 'ready',
        pending: 26,
        updated_at: '2026-03-18T12:07:15+00:00',
      };
      overviewState = {
        ...overviewState,
        results: {
          ...overviewState.results,
          headline: 'Fila reaberta',
          summary: 'Os contatos ja processados permanecem no historico, enquanto a nova fila aguarda o proximo envio.',
          distribution: { sent: 237, failed: 0, pending: 26, invalid: 1, valid: 263, total: 264 },
          reprocessing: {
            active: true,
            mode: 'failed',
            reset_contacts: 26,
            queued_contacts: 26,
            sent_in_reprocessing: 0,
            failed_in_reprocessing: 0,
          },
        },
      };
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        message: mode === 'failed' ? 'Fila recriada para reenviar so as falhas.' : 'Fila recriada para reenviar toda a campanha.',
        reset_contacts: mode === 'failed' ? 26 : 238,
        new_status: 'ready',
      }),
    });
  });

  await page.route('**/campaigns/*/dry-run', async (route) => {
    await page.waitForTimeout(250);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        message: 'Esta ação não envia mensagens reais. Existem 1 contatos prontos para envio.',
        pending_count: 1,
        summary: {
          valid: 1,
          invalid: 0,
          total: 1,
        },
        preview: [
          {
            name: 'Cliente E2E',
            phone: '+5581999999999',
            message: 'Oi, Cliente E2E! Mensagem E2E',
          },
        ],
        estimated_seconds: 7,
        empty_reason: null,
      }),
    });
  });

  await page.route('**/campaigns/*/test-run', async (route) => {
    await page.waitForTimeout(250);
    statsState = {
      ...statsState,
      test_completed_at: '2026-03-18T12:03:00+00:00',
      updated_at: '2026-03-18T12:03:00+00:00',
    };
    overviewState = {
      ...overviewState,
      activity: {
        ...overviewState.activity,
        total_events: 1,
        summary_cards: [
          { key: 'state', label: 'Mudancas de estado', count: 1, tone: 'info' },
          { key: 'success', label: 'Entregas confirmadas', count: 0, tone: 'success' },
          { key: 'retry', label: 'Novas tentativas', count: 0, tone: 'warn' },
          { key: 'failure', label: 'Falhas tecnicas', count: 0, tone: 'error' },
        ],
        milestones: [
          { title: 'Campanha iniciada', summary: 'O envio real foi liberado e a campanha entrou em execucao.', time: '2026-03-18T12:03:00+00:00', tone: 'info' },
        ],
        incidents: [],
      },
    };
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        sent: 1,
        failures: 0,
        message: 'Amostra enviada para confirmacao.',
        destination_note: 'Mesmo número conectado',
        failure_reasons: {},
        failure_details: [],
        hint: '',
      }),
    });
  });

  await page.route('**/campaigns/*/start', async (route) => {
    sessionState = {
      ...sessionState,
      lastError: "Attempted to use detached Frame 'frame-1'.",
    };
    statsState = {
      ...statsState,
      status: 'running',
      started_at: '2026-03-18T12:04:00+00:00',
      updated_at: '2026-03-18T12:04:00+00:00',
      pause_reason: null,
      sent_today: 0,
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
        ...statsState.estimates,
        remaining_seconds_observed: 0,
        label_speed: 'Aquecendo medicao',
        label_eta: 'Calculando com base na execucao real',
      },
    };
    overviewState = {
      ...overviewState,
      results: {
        ...overviewState.results,
        headline: 'Campanha em andamento',
        summary: 'A execucao segue ativa.',
        processed: 0,
        distribution: { sent: 0, failed: 0, pending: 1, invalid: 0, valid: 1, total: 1 },
        started_at: '2026-03-18T12:04:00+00:00',
        finished_at: null,
      },
      activity: {
        ...overviewState.activity,
        total_events: 2,
        summary_cards: [
          { key: 'state', label: 'Mudancas de estado', count: 2, tone: 'info' },
          { key: 'success', label: 'Entregas confirmadas', count: 0, tone: 'success' },
          { key: 'retry', label: 'Novas tentativas', count: 0, tone: 'warn' },
          { key: 'failure', label: 'Falhas tecnicas', count: 0, tone: 'error' },
        ],
        milestones: [
          { title: 'Campanha iniciada', summary: 'O envio real foi liberado e a campanha entrou em execucao.', time: '2026-03-18T12:04:00+00:00', tone: 'info' },
        ],
        incidents: [],
      },
    };
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, message: 'Campanha iniciada' }),
    });
  });

  await page.route('**/campaigns/*/pause', async (route) => {
    statsState = {
      ...statsState,
      status: 'paused',
      updated_at: '2026-03-18T12:05:00+00:00',
      pause_reason: 'consecutive_failures',
    };
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, message: 'Campanha pausada' }),
    });
  });

  await page.route('**/campaigns/*/resume', async (route) => {
    statsState = {
      ...statsState,
      status: 'running',
      sent: 1,
      pending: 0,
      updated_at: '2026-03-18T12:06:00+00:00',
      sent_today: 1,
      pause_reason: null,
      performance: {
        observed_contacts_per_minute: 1.2,
        observed_seconds_per_contact: 50,
        measurement_window_seconds: 600,
        measurement_basis: 'recent_window',
        last_activity_at: '2026-03-18T12:05:50+00:00',
        sample_size: 4,
        warming_up: false,
      },
      estimates: {
        ...statsState.estimates,
        remaining_seconds_observed: 0,
        remaining_seconds_conservative: 0,
        label_speed: '1,2 contato/min',
        label_eta: '0',
      },
    };
    overviewState = {
      results: {
        headline: 'Campanha concluida',
        summary: 'Resultado final sem incidentes relevantes.',
        processed: 1,
        success_rate: 100,
        failure_rate: 0,
        coverage_rate: 100,
        duration_seconds: 120,
        distribution: {
          sent: 1,
          failed: 0,
          pending: 0,
          invalid: 0,
          valid: 1,
          total: 1,
        },
        top_failures: [],
        started_at: '2026-03-18T12:04:00+00:00',
        finished_at: '2026-03-18T12:06:00+00:00',
      },
      activity: {
        total_events: 4,
        summary_cards: [
          { key: 'state', label: 'Mudancas de estado', count: 3, tone: 'info' },
          { key: 'success', label: 'Entregas confirmadas', count: 1, tone: 'success' },
          { key: 'retry', label: 'Novas tentativas', count: 0, tone: 'warn' },
          { key: 'failure', label: 'Falhas tecnicas', count: 0, tone: 'error' },
        ],
        milestones: [
          { title: 'Campanha concluida', summary: 'A campanha terminou e encerrou a fila atual.', time: '2026-03-18T12:06:00+00:00', tone: 'success' },
          { title: 'Campanha iniciada', summary: 'O envio real foi liberado e a campanha entrou em execucao.', time: '2026-03-18T12:04:00+00:00', tone: 'info' },
          { title: 'Lote processado', summary: 'Lote de 1 contatos processado.', time: '2026-03-18T12:05:50+00:00', tone: 'success' },
        ],
        incidents: [
          {
            title: 'Falha de envio',
            summary: 'Sistema de envio indisponivel',
            tone: 'error',
            count: 4,
            time: '2026-03-18T12:05:40+00:00',
            error_class: 'temporary',
            http_status: 503,
            human_title: 'Bridge indisponivel',
            human_summary: 'O servico de envio nao respondeu no momento da tentativa.',
            recommended_action: 'Verifique o wa-bridge e a conectividade local.',
            technical_summary: 'All connection attempts failed',
            technical_detail_available: true,
            fingerprint: 'send_failure:bridge_unreachable:503',
          },
        ],
      },
    };
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, message: 'Campanha retomada' }),
    });
  });

  await page.route('**/campaigns/*/cancel', async (route) => {
    statsState = {
      ...statsState,
      status: 'cancelled',
      updated_at: '2026-03-18T12:06:30+00:00',
    };
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, message: 'Campanha cancelada' }),
    });
  });

  await page.goto('/login');
  await expect(page.getByRole('heading', { name: 'Mass Sender' })).toBeVisible();
  await page.getByPlaceholder('Senha').fill('admin123');
  await page.getByRole('button', { name: 'Entrar' }).click();

  await expect(page.getByRole('heading', { name: 'Campanhas' })).toBeVisible();
  await expect(page.getByText('Canal WhatsApp')).toBeVisible();
  await expect(page.getByText('Sessao pronta para conectar um numero.')).toBeVisible();
  await page.getByRole('button', { name: 'Gerar QR para conectar' }).click();
  await expect(page.locator('#qr-image')).toHaveAttribute('src', /data:image\/png;base64/);
  await expect(page.getByText('Numero conectado e pronto para envio')).toBeVisible();

  await page.locator('input[name="name"]').fill('Campanha E2E');
  await page.getByRole('button', { name: 'Criar campanha' }).click();

  await expect(page).toHaveURL(/\/campaigns\/\d+$/);
  await expect(page.locator('h1')).toBeVisible();
  await expect(page.locator('[data-testid="campaign-stepper"]')).toBeVisible();
  await expect(page.getByText('Configuracoes operacionais')).toBeVisible();
  await expect(page.locator('#speed-profile-badge')).toContainText('Conservador');
  await page.getByRole('button', { name: 'Agressivo' }).click();
  await expect(page.locator('#settings-form input[name="send_delay_min_seconds"]')).toHaveValue('3');
  await expect(page.locator('#settings-form input[name="batch_pause_max_seconds"]')).toHaveValue('10');
  await expect(page.locator('#speed-profile-badge')).toContainText('Agressivo');
  await page.locator('#settings-form input[name="send_delay_min_seconds"]').fill('18');
  await page.locator('#settings-form input[name="send_delay_max_seconds"]').fill('48');
  await page.locator('#settings-form input[name="batch_pause_min_seconds"]').fill('11');
  await page.locator('#settings-form input[name="batch_pause_max_seconds"]').fill('16');
  await page.locator('#settings-form input[name="daily_limit"]').fill('250');
  await expect(page.locator('#speed-profile-badge')).toContainText('Customizado');
  await page.getByRole('button', { name: 'Salvar configuracoes' }).click();
  await expect(page.getByText('Configuracoes operacionais salvas.')).toBeVisible();
  await expect(page.locator('[data-testid="status-narrative"]')).toContainText('Configure sua campanha para validar contatos antes do envio.');
  await expect(page.getByRole('button', { name: 'Simular campanha' })).toBeVisible();
  await expect(page.locator('[data-testid="primary-action"]')).toContainText('Simular campanha');
  await expect(page.locator('[data-testid="status-filter-trigger"]')).toHaveText(/Todos/);
  await expect(page.locator('#contacts-meta')).toContainText('Pagina 1 de 3');
  await page.locator('[data-testid="status-filter-trigger"]').click();
  await page.getByRole('option', { name: 'Falhas' }).click();
  await expect(page.locator('[data-testid="status-filter-trigger"]')).toHaveText(/Falhas/);
  await expect(page.locator('#contacts-per-page')).toHaveValue('10');
  await expect(page.locator('#contacts-body tr')).toHaveCount(10);
  await expect(page.locator('#contacts-meta')).toContainText('Total exibido: 10 de 26 registros. Pagina 1 de 3.');
  await page.getByRole('button', { name: 'Proxima' }).click();
  await expect(page.locator('#contacts-meta')).toContainText('Total exibido: 10 de 26 registros. Pagina 2 de 3.');
  await expect(page.locator('#contacts-body')).toContainText('Cliente 11');
  await page.getByRole('button', { name: 'Anterior' }).click();
  await expect(page.locator('#contacts-meta')).toContainText('Total exibido: 10 de 26 registros. Pagina 1 de 3.');

  await page.getByRole('button', { name: 'Adicionar manualmente' }).click();
  await page.locator('#manual-contact-form input[name="name"]').fill('Cliente Manual');
  await page.locator('#manual-contact-form input[name="phone"]').fill('1234');
  await page.getByRole('button', { name: 'Salvar cliente' }).click();
  await expect(page.locator('#manual-contact-feedback')).toContainText('Formato inválido para Brasil (+55)');
  await page.locator('#manual-contact-form input[name="phone"]').fill('+55 81999999999');
  await page.locator('#manual-contact-form input[name="email"]').fill('manual@cliente.com');
  await page.getByRole('button', { name: 'Salvar cliente' }).click();
  await expect(page.getByText('Cliente adicionado manualmente.')).toBeVisible();

  await page.locator('#contacts-body').getByRole('button', { name: 'Excluir' }).first().click();
  await expect(page.locator('#confirm-title')).toContainText('Excluir contato da campanha');
  await page.getByRole('button', { name: 'Confirmar' }).click();
  await expect(page.getByText('Contato removido da campanha com sucesso.')).toBeVisible();
  expect(deleteContactCalled).toBeTruthy();

  await page.getByRole('button', { name: 'Limpar base importada' }).click();
  await expect(page.locator('#confirm-title')).toContainText('Limpar base importada');
  await page.getByRole('button', { name: 'Confirmar' }).click();
  await expect(page.getByText('Contatos importados removidos com sucesso.')).toBeVisible();
  await expect(page.locator('#contacts-meta')).toContainText('Total exibido: 0 de 0 registros. Pagina 1 de 1.');
  expect(deleteImportedCalled).toBeTruthy();

  await page.locator('textarea[name="message_template"]').fill('Oi, {{nome}}! Mensagem E2E');
  await page.getByRole('button', { name: 'Salvar mensagem' }).click();

  await page.setInputFiles('input[name="csv_file"]', path.resolve(__dirname, '../fixtures/contatos_e2e.csv'));
  await expect
    .poll(async () =>
      page.locator('input[name="csv_file"]').evaluate((element) => {
        return element instanceof HTMLInputElement ? element.files?.[0]?.name || '' : '';
      }),
    )
    .toBe('contatos_e2e.csv');
  await page.getByRole('button', { name: 'Enviar CSV' }).click();
  await expect(page.getByText('Upload concluido com sucesso.')).toBeVisible();
  await expect(page.locator('#upload-summary')).toContainText('2 contatos prontos para envio');
  await expect(page.locator('[data-testid="status-filter-trigger"]')).toHaveText(/Todos/);
  await expect(page.locator('#contacts-body')).toContainText('Cliente E2E');

  const dryRunPromise = page.getByRole('button', { name: 'Simular campanha' }).click();
  await expect(page.locator('[data-testid="status-narrative"]')).toContainText('Processando simulacao da campanha...');
  await dryRunPromise;
  await expect(page.locator('[data-testid="status-narrative"]')).toContainText('Tudo pronto para uma verificacao final.');
  await expect(page.getByText('Tempo estimado')).toBeVisible();
  await expect(page.locator('#eta-value')).toContainText('Estimando');
  await expect(page.locator('#speed-value')).toContainText('Medindo');
  await expect(page.locator('#runtime-profile-badge')).toContainText('Perfil customizado');

  const testRunPromise = page.getByRole('button', { name: 'Enviar teste' }).click();
  await expect(page.locator('[data-testid="status-narrative"]')).toContainText('Processando inicio de teste...');
  await testRunPromise;
  await expect(page.getByText('Amostra enviada para confirmacao.')).toBeVisible();
  await expect(page.locator('[data-testid="primary-action"]')).toContainText('Iniciar campanha');

  await page.getByRole('button', { name: 'Iniciar campanha' }).click();
  await expect(page.locator('[data-testid="status-narrative"]')).toContainText(/Envio em risco|Fila travada em processamento/);
  await expect(page.locator('[data-testid="primary-action"]')).toContainText('Pausar campanha');
  await expect(page.locator('[data-testid="execution-progress-bar"]')).toBeVisible();
  await expect(page.locator('#speed-note')).toContainText('Config. 18-48s + pausas');
  await expect(page.locator('#daily-limit-summary')).toContainText('Hoje: 0 / 250 envios');
  await page.getByRole('button', { name: 'Conservador' }).click();
  await expect(page.locator('#confirm-title')).toContainText('Aplicar novo modo de velocidade');
  await page.getByRole('button', { name: 'Aplicar modo' }).click();
  await expect(page.locator('#runtime-profile-badge')).toContainText('Perfil conservador');
  await expect(page.locator('#speed-note')).toContainText('Config. 5-10s + pausas');
  await page.getByRole('button', { name: 'Minimizar' }).click();
  await expect(page.locator('[data-testid="execution-progress-bar"]')).toHaveClass(/is-collapsed/);
  await expect(page.locator('#execution-progress-pill')).toBeVisible();
  await page.locator('#execution-progress-pill').click();
  await expect(page.locator('#execution-progress-pill')).toHaveClass(/hidden/);
  await page.getByRole('button', { name: 'Abortar' }).click();
  await expect(page.locator('#confirm-title')).toContainText('Abortar envio da campanha');
  await expect(page.locator('#confirm-cancel')).toBeFocused();
  await page.locator('#confirm-cancel').click();

  await page.getByRole('button', { name: 'Pausar campanha' }).click();
  await expect(page.locator('[data-testid="status-narrative"]')).toContainText('falhas consecutivas');
  await expect(page.locator('[data-testid="primary-action"]')).toContainText('Retomar campanha');

  await page.getByRole('button', { name: 'Retomar campanha' }).click();
  await page.waitForTimeout(13000);
  statsState = {
    ...statsState,
    status: 'completed',
    finished_at: '2026-03-18T12:07:00+00:00',
    updated_at: '2026-03-18T12:07:00+00:00',
  };
  overviewFailureCountdown = 2;
  await page.reload();
  await page.waitForTimeout(6500);

  await expect(page.locator('[data-testid="status-narrative"]')).toContainText('Campanha finalizada com sucesso.');
  await expect(page.locator('[data-testid="primary-action"]')).toContainText('Ver resultados');
  await expect(page.getByText('Falha temporaria ao carregar resultados e atividade detalhados.')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Ver resultados' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Exportar falhas' })).toBeVisible();
  await expect(page.locator('.stepper-item[data-step-key="3"]')).toHaveAttribute('data-step-state', 'done');
  await expect(page.locator('.stepper-item[data-step-key="4"]')).toHaveAttribute('data-step-state', 'done');
  await expect(page.locator('.stepper-item[data-step-key="5"]')).toHaveAttribute('data-step-state', 'done');
  await page.getByRole('button', { name: 'Ver resultados' }).click();
  await expect(page.locator('[data-testid="results-section"]')).toBeFocused();
  await expect(page.locator('#results-headline')).toContainText('Campanha concluida');
  await expect(page.locator('#results-success-rate')).toContainText('100%');
  await expect(page.locator('#results-distribution')).toContainText('Enviados');
  const reprocessButton = page.getByRole('button', { name: 'Reprocessar falhados' });
  if (await reprocessButton.count()) {
    await expect(reprocessButton).toBeVisible();
    await reprocessButton.click();
    await expect(page.locator('#confirm-title')).toContainText('Reprocessar falhados');
    await page.getByRole('button', { name: 'Confirmar' }).click();
    await expect.poll(() => failedReprocessingCalled).toBeTruthy();
    await expect(page.locator('#campaign-status-badge')).toContainText('Pronta');
    await expect(page.locator('#results-reprocessing')).toContainText('Reprocessamento de falhas');
    await expect(page.locator('#results-reprocessing')).toContainText('26 contatos reenfileirados');
  }

  statsState = {
    ...statsState,
    test_completed_at: null,
  };
  await page.getByRole('button', { name: 'Adicionar manualmente' }).click();
  await page.locator('#manual-contact-form input[name="name"]').fill('Novo apos concluida');
  await page.locator('#manual-contact-form input[name="phone"]').fill('+55 81999999998');
  await page.getByRole('button', { name: 'Salvar cliente' }).click();
  await expect(page.getByText('Cliente adicionado manualmente.')).toBeVisible();
  await expect(page.locator('#campaign-status-badge')).toContainText('Pronta');
  await expect(page.locator('[data-testid="primary-action"]')).toContainText('Iniciar campanha', { timeout: 10000 });

  statsState = {
    ...statsState,
    status: 'cancelled',
    finished_at: '2026-03-18T12:08:00+00:00',
    updated_at: '2026-03-18T12:08:00+00:00',
  };
  await page.reload();
  await expect(page.locator('[data-testid="primary-action"]')).toContainText('Reiniciar campanha');
  await expect(page.getByRole('button', { name: 'Reiniciar campanha' })).toHaveCount(1);

  await page.getByRole('button', { name: 'Mostrar logs' }).click();
  await expect(page.locator('[data-testid="logs-panel"]')).toContainText('Incidentes agrupados');
  await expect(page.locator('#activity-summary-grid')).toContainText('Entregas confirmadas');
  await expect(page.locator('#activity-incidents')).toContainText('Bridge indisponivel');
  await expect(page.locator('#activity-incidents')).toContainText('Verifique o wa-bridge e a conectividade local.');
  await expect(page.locator('#activity-milestones')).toContainText('Campanha concluida');
  await expect(page.locator('#activity-milestones')).toContainText('Campanha iniciada');
  await expect(page.locator('#activity-milestones')).toContainText('Lote processado');

  await page.setViewportSize({ width: 960, height: 700 });
  await expect(page.locator('[data-testid="contacts-table-wrap"]')).toBeVisible();
  await page.setViewportSize({ width: 430, height: 932 });
  await expect(page.locator('[data-testid="contacts-table-wrap"]')).toBeVisible();

  await page.getByRole('link', { name: /Voltar/ }).click();
  await expect(page.getByRole('heading', { name: 'Campanhas' })).toBeVisible();
  await page.getByRole('button', { name: 'Excluir' }).first().click();
  await expect(page.locator('#bridge-confirm-title')).toContainText('Excluir campanha');
  await page.getByRole('button', { name: 'Confirmar' }).click();
  await expect(page.getByText('Campanha excluida com sucesso.')).toBeVisible();
  expect(deleteCampaignCalled).toBeTruthy();
});
