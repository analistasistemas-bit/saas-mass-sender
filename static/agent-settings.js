(function () {
  const page = document.querySelector('[data-agent-settings-page="true"]');
  if (!page) return;

  const toastRegion = document.getElementById('agent-settings-toast-region');
  const tabButtons = Array.from(document.querySelectorAll('.agent-tab-button'));
  const tabPanels = Array.from(document.querySelectorAll('[data-tab-panel]'));
  const saveButtons = Array.from(document.querySelectorAll('[data-save-tab]'));
  const statusBadge = document.getElementById('agent-settings-status-badge');
  const statusText = document.getElementById('agent-settings-status-text');
  const summaryModel = document.getElementById('agent-settings-summary-model');
  const summaryPriority = document.getElementById('agent-settings-summary-priority');

  const state = {
    config: null,
    availableModels: [],
    priority: ['manual', 'spreadsheet', 'database'],
    latestUpload: null,
    simulatorHistory: [],
    simulatorAiReplies: 0,
  };

  function showToast(type, message) {
    const item = document.createElement('div');
    item.className = `toast toast--${type}`;
    item.innerHTML = `<div><p class="font-medium text-ink">${message}</p></div>`;
    toastRegion?.appendChild(item);
    window.setTimeout(() => item.remove(), 3600);
  }

  function setButtonLoading(button, label, active) {
    if (!button) return;
    if (active) {
      if (!button.dataset.originalLabel) button.dataset.originalLabel = button.textContent || '';
      button.disabled = true;
      button.innerHTML = `<span class="button-spinner" aria-hidden="true"></span><span>${label}</span>`;
      return;
    }
    button.textContent = button.dataset.originalLabel || button.textContent || '';
    button.disabled = false;
  }

  function activateTab(tab) {
    tabButtons.forEach((button) => button.classList.toggle('is-active', button.dataset.tab === tab));
    tabPanels.forEach((panel) => panel.classList.toggle('hidden', panel.dataset.tabPanel !== tab));
  }

  function fillSelect(select, items, selected) {
    if (!select) return;
    select.innerHTML = '';
    const safeItems = Array.isArray(items) && items.length ? items : [''];
    safeItems.forEach((item) => {
      const option = document.createElement('option');
      option.value = item;
      option.textContent = item || 'Selecione';
      select.appendChild(option);
    });
    select.value = selected && safeItems.includes(selected) ? selected : safeItems[0];
  }

  function setValue(id, value) {
    const el = document.getElementById(id);
    if (!el) return;
    if (el.type === 'checkbox') {
      el.checked = Boolean(value);
      return;
    }
    el.value = value ?? '';
  }

  function payloadForTab(tab) {
    if (tab === 'inbound') {
      return {
        inbound_ai_enabled: document.getElementById('inbound-ai-enabled')?.checked,
        primary_model: document.getElementById('primary-model')?.value,
        business_name: document.getElementById('business-name')?.value,
      };
    }
    if (tab === 'personality') {
      return {
        agent_name: document.getElementById('agent-name')?.value,
        tone: document.getElementById('tone')?.value,
        style: document.getElementById('style')?.value,
        proactivity_level: document.getElementById('proactivity-level')?.value,
        use_emojis: document.getElementById('use-emojis')?.checked,
        max_response_length: document.getElementById('max-response-length')?.value,
        personality_instructions: document.getElementById('personality-instructions')?.value,
      };
    }
    if (tab === 'behavior') {
      return {
        can_answer_price: document.getElementById('can-answer-price')?.checked,
        can_answer_stock: document.getElementById('can-answer-stock')?.checked,
        can_answer_description: document.getElementById('can-answer-description')?.checked,
        can_suggest_similar_products: document.getElementById('can-suggest-similar-products')?.checked,
        can_negotiate_discount: document.getElementById('can-negotiate-discount')?.checked,
        can_close_order: document.getElementById('can-close-order')?.checked,
        handoff_on_order_intent: document.getElementById('handoff-on-order-intent')?.checked,
        handoff_on_low_confidence: document.getElementById('handoff-on-low-confidence')?.checked,
        handoff_on_human_request: document.getElementById('handoff-on-human-request')?.checked,
        max_auto_replies_per_conversation: Number(document.getElementById('max-auto-replies')?.value || 5),
        response_delay_min_ms: Number(document.getElementById('response-delay-min-ms')?.value || 1000),
        response_delay_max_ms: Number(document.getElementById('response-delay-max-ms')?.value || 3000),
      };
    }
    if (tab === 'handoff') {
      return {
        handoff_enabled: document.getElementById('handoff-enabled')?.checked,
        handoff_message: document.getElementById('handoff-message')?.value,
        human_whatsapp_number: document.getElementById('human-whatsapp-number')?.value,
        stop_ai_after_handoff: document.getElementById('stop-ai-after-handoff')?.checked,
      };
    }
    if (tab === 'manual') {
      return {
        manual_knowledge_enabled: document.getElementById('manual-knowledge-enabled')?.checked,
        manual_knowledge_text: document.getElementById('manual-knowledge-text')?.value,
      };
    }
    if (tab === 'database') {
      return {
        db_enabled: document.getElementById('db-enabled')?.checked,
        db_type: document.getElementById('db-type')?.value,
        db_host: document.getElementById('db-host')?.value,
        db_port: Number(document.getElementById('db-port')?.value || 1521),
        db_service: document.getElementById('db-service')?.value,
        db_user: document.getElementById('db-user')?.value,
        db_password: document.getElementById('db-password')?.value,
        db_view_name: document.getElementById('db-view-name')?.value,
        db_timeout_seconds: Number(document.getElementById('db-timeout-seconds')?.value || 5),
      };
    }
    if (tab === 'priority') {
      return { knowledge_priority: state.priority.slice() };
    }
    return {};
  }

  function renderSummary() {
    const enabled = Boolean(state.config?.summary?.enabled);
    statusBadge.className = `status-badge ${enabled ? 'status-badge--success' : 'status-badge--warn'}`;
    statusBadge.textContent = enabled ? 'Agente ativo' : 'Agente pausado';
    statusText.textContent = enabled ? 'Inbound liberado para respostas automáticas.' : 'Inbound registrado sem resposta automática.';
    summaryModel.textContent = state.config?.summary?.primary_model || '-';
    summaryPriority.textContent = state.priority.join(' → ');
  }

  function renderPriority() {
    const root = document.getElementById('priority-list');
    if (!root) return;
    root.innerHTML = '';
    state.priority.forEach((item, index) => {
      const card = document.createElement('div');
      card.className = 'flex items-center justify-between rounded-2xl border border-line bg-shell px-4 py-4';
      card.innerHTML = `
        <div>
          <p class="text-xs font-semibold uppercase tracking-[0.18em] text-muted">Posição ${index + 1}</p>
          <p class="mt-1 text-sm font-semibold text-ink">${item}</p>
        </div>
        <div class="flex gap-2">
          <button type="button" class="secondary-button" data-priority-up="${item}">Subir</button>
          <button type="button" class="secondary-button" data-priority-down="${item}">Descer</button>
        </div>
      `;
      root.appendChild(card);
    });
  }

  function renderSimulatorHistory() {
    const root = document.getElementById('simulator-history');
    const badge = document.getElementById('simulator-history-badge');
    if (badge) {
      badge.textContent = `${state.simulatorHistory.length} ${state.simulatorHistory.length === 1 ? 'mensagem' : 'mensagens'}`;
      badge.className = `status-badge ${state.simulatorHistory.length ? 'status-badge--success' : 'status-badge--info'}`;
    }
    if (!root) return;
    if (!state.simulatorHistory.length) {
      root.innerHTML =
        '<div class="simulator-thread__empty"><p class="text-sm text-muted">O simulador começa limpo. Cada teste adiciona a nova mensagem do cliente e a resposta gerada pela IA.</p></div>';
      return;
    }

    root.innerHTML = '';
    state.simulatorHistory.forEach((item) => {
      const card = document.createElement('div');
      const isAssistant = item.role === 'assistant';
      card.className = `simulator-bubble ${isAssistant ? 'simulator-bubble--assistant' : 'simulator-bubble--user'}`;
      card.innerHTML = `
        <p class="simulator-bubble__role ${isAssistant ? 'simulator-bubble__role--assistant' : 'simulator-bubble__role--user'}">
          ${isAssistant ? 'Agente' : 'Cliente'}
        </p>
        <p class="simulator-bubble__text"></p>
      `;
      card.querySelector('p:last-child').textContent = item.text || '';
      root.appendChild(card);
    });
    root.scrollTop = root.scrollHeight;
  }

  function resetSimulator() {
    state.simulatorHistory = [];
    state.simulatorAiReplies = 0;
    const badge = document.getElementById('simulator-result-badge');
    const meta = document.getElementById('simulator-result-meta');
    const text = document.getElementById('simulator-result-text');
    const prompt = document.getElementById('simulator-prompt');
    if (badge) {
      badge.className = 'status-badge status-badge--info';
      badge.textContent = 'Aguardando';
    }
    if (meta) {
      meta.textContent = 'O simulador vai mostrar decisão, tempo, fonte e produto encontrado.';
    }
    if (text) {
      text.textContent = 'Nenhum teste executado.';
    }
    if (prompt) {
      prompt.value = '';
    }
    renderSimulatorHistory();
  }

  function renderSpreadsheet(upload) {
    state.latestUpload = upload || null;
    const meta = document.getElementById('spreadsheet-upload-meta');
    const mappingRoot = document.getElementById('spreadsheet-mapping');
    const previewRoot = document.getElementById('spreadsheet-preview');
    const deleteButton = document.getElementById('spreadsheet-delete-button');
    if (!upload) {
      if (meta) meta.textContent = 'Nenhum upload recente.';
      if (mappingRoot) mappingRoot.innerHTML = '';
      if (previewRoot) previewRoot.innerHTML = '<div class="p-6 text-sm text-muted">Faça upload para visualizar preview e mapeamento.</div>';
      if (deleteButton) deleteButton.disabled = true;
      return;
    }

    if (meta) {
      meta.textContent = `${upload.file_name} · ${upload.validation_status} · ${upload.is_active ? 'ativo' : 'pendente de ativação'}`;
    }
    if (deleteButton) deleteButton.disabled = false;

    const columns = upload.columns || [];
    const current = upload.mapping || {};
    const fields = [
      ['name', 'nome'],
      ['code', 'código'],
      ['description', 'descrição'],
      ['price', 'preço'],
      ['stock', 'estoque'],
      ['category', 'categoria'],
    ];

    if (mappingRoot) {
      mappingRoot.innerHTML = '';
      fields.forEach(([key, label]) => {
        const wrap = document.createElement('label');
        wrap.className = 'agent-field';
        const select = document.createElement('select');
        select.className = 'agent-input';
        select.dataset.mappingField = key;
        const empty = document.createElement('option');
        empty.value = '';
        empty.textContent = `Sem mapeamento`;
        select.appendChild(empty);
        columns.forEach((column) => {
          const option = document.createElement('option');
          option.value = column;
          option.textContent = column;
          select.appendChild(option);
        });
        select.value = current[key] || '';
        wrap.innerHTML = `<span class="agent-field__label">${label}</span>`;
        wrap.appendChild(select);
        mappingRoot.appendChild(wrap);
      });
    }

    if (previewRoot) {
      const rows = upload.preview_rows || [];
      if (!rows.length) {
        previewRoot.innerHTML = '<div class="p-6 text-sm text-muted">O arquivo não trouxe linhas para preview.</div>';
        return;
      }
      const table = document.createElement('table');
      table.className = 'min-w-full divide-y divide-line text-sm';
      const headers = Object.keys(rows[0]);
      table.innerHTML = `
        <thead class="bg-shell">
          <tr>${headers.map((header) => `<th class="px-3 py-2 text-left font-semibold text-muted">${header}</th>`).join('')}</tr>
        </thead>
        <tbody class="divide-y divide-line bg-white">
          ${rows
            .map(
              (row) =>
                `<tr>${headers.map((header) => `<td class="px-3 py-2 text-ink">${row[header] ?? ''}</td>`).join('')}</tr>`
            )
            .join('')}
        </tbody>
      `;
      previewRoot.innerHTML = '';
      previewRoot.appendChild(table);
    }
  }

  function hydrate(config) {
    state.config = config;
    state.availableModels = config.available_models || [];
    state.priority = config.priority?.knowledge_priority || ['manual', 'spreadsheet', 'database'];
    setValue('inbound-ai-enabled', config.inbound?.inbound_ai_enabled);
    setValue('business-name', config.inbound?.business_name);
    setValue('agent-name', config.personality?.agent_name);
    setValue('tone', config.personality?.tone);
    setValue('style', config.personality?.style);
    setValue('proactivity-level', config.personality?.proactivity_level);
    setValue('use-emojis', config.personality?.use_emojis);
    setValue('max-response-length', config.personality?.max_response_length);
    setValue('personality-instructions', config.personality?.personality_instructions);
    setValue('can-answer-price', config.behavior?.can_answer_price);
    setValue('can-answer-stock', config.behavior?.can_answer_stock);
    setValue('can-answer-description', config.behavior?.can_answer_description);
    setValue('can-suggest-similar-products', config.behavior?.can_suggest_similar_products);
    setValue('can-negotiate-discount', config.behavior?.can_negotiate_discount);
    setValue('can-close-order', config.behavior?.can_close_order);
    setValue('handoff-on-order-intent', config.behavior?.handoff_on_order_intent);
    setValue('handoff-on-low-confidence', config.behavior?.handoff_on_low_confidence);
    setValue('handoff-on-human-request', config.behavior?.handoff_on_human_request);
    setValue('max-auto-replies', config.behavior?.max_auto_replies_per_conversation);
    setValue('response-delay-min-ms', config.behavior?.response_delay_min_ms);
    setValue('response-delay-max-ms', config.behavior?.response_delay_max_ms);
    setValue('handoff-enabled', config.handoff?.handoff_enabled);
    setValue('handoff-message', config.handoff?.handoff_message);
    setValue('human-whatsapp-number', config.handoff?.human_whatsapp_number);
    setValue('stop-ai-after-handoff', config.handoff?.stop_ai_after_handoff);
    setValue('manual-knowledge-enabled', config.manual?.manual_knowledge_enabled);
    setValue('manual-knowledge-text', config.manual?.manual_knowledge_text);
    setValue('db-enabled', config.database?.db_enabled);
    setValue('db-type', config.database?.db_type);
    setValue('db-host', config.database?.db_host);
    setValue('db-port', config.database?.db_port);
    setValue('db-service', config.database?.db_service);
    setValue('db-user', config.database?.db_user);
    setValue('db-view-name', config.database?.db_view_name);
    setValue('db-timeout-seconds', config.database?.db_timeout_seconds);
    document.getElementById('db-password').value = '';
    fillSelect(document.getElementById('primary-model'), state.availableModels, config.inbound?.primary_model);
    fillSelect(document.getElementById('test-model'), state.availableModels, config.inbound?.primary_model);
    fillSelect(document.getElementById('simulator-model'), [''].concat(state.availableModels), '');
    renderSpreadsheet(config.spreadsheet?.latest_upload || config.spreadsheet?.active_upload || null);
    renderPriority();
    renderSummary();
  }

  async function loadConfig(showErrors) {
    try {
      const response = await fetch('/agent-settings/config');
      const data = await response.json();
      if (!response.ok || data.ok === false) throw new Error(data.message || 'Falha ao carregar a configuração.');
      hydrate(data);
    } catch (error) {
      if (showErrors) showToast('error', String(error.message || error));
    }
  }

  async function saveTab(tab, button) {
    setButtonLoading(button, 'Salvando...', true);
    try {
      const response = await fetch(`/agent-settings/config/${tab}`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payloadForTab(tab)),
      });
      const data = await response.json();
      if (!response.ok || data.ok === false) throw new Error(data.message || 'Falha ao salvar.');
      hydrate(data);
      showToast('success', 'Configuração salva.');
    } catch (error) {
      showToast('error', String(error.message || error));
    } finally {
      setButtonLoading(button, 'Salvando...', false);
    }
  }

  async function runInboundTest() {
    const button = document.getElementById('run-inbound-test');
    setButtonLoading(button, 'Testando...', true);
    try {
      const response = await fetch('/inbound/ai-model/test', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          model: document.getElementById('test-model')?.value,
          prompt: document.getElementById('test-prompt')?.value,
        }),
      });
      const data = await response.json();
      if (!response.ok || data.ok === false) throw new Error(data.message || 'Falha ao testar modelo.');
      const badge = document.getElementById('inbound-test-badge');
      const meta = document.getElementById('inbound-test-meta');
      const text = document.getElementById('inbound-test-response');
      const tone = data.action === 'handoff' ? 'status-badge--warn' : 'status-badge--success';
      badge.className = `status-badge ${tone}`;
      badge.textContent = data.action === 'handoff' ? 'Handoff' : 'Resposta';
      meta.textContent = `Modelo: ${data.model} · Fonte: ${data.source || 'none'} · Confiança: ${data.confidence ?? '-'} · Tempo: ${data.elapsed_ms ?? 0} ms`;
      text.textContent = data.preview_text || '(sem conteúdo)';
    } catch (error) {
      showToast('error', String(error.message || error));
    } finally {
      setButtonLoading(button, 'Testando...', false);
    }
  }

  async function uploadSpreadsheet() {
    const input = document.getElementById('spreadsheet-file');
    const button = document.getElementById('spreadsheet-upload-button');
    const file = input?.files?.[0];
    if (!file) {
      showToast('error', 'Escolha um arquivo antes de enviar.');
      return;
    }
    const form = new FormData();
    form.append('file', file);
    setButtonLoading(button, 'Enviando...', true);
    try {
      const response = await fetch('/agent-settings/spreadsheet/upload', { method: 'POST', body: form });
      const data = await response.json();
      if (!response.ok || data.ok === false) throw new Error(data.message || 'Falha ao enviar a planilha.');
      renderSpreadsheet(data.upload);
      showToast('success', 'Planilha validada. Revise o preview e ative quando estiver pronta.');
    } catch (error) {
      showToast('error', String(error.message || error));
    } finally {
      setButtonLoading(button, 'Enviando...', false);
    }
  }

  async function activateSpreadsheet() {
    if (!state.latestUpload?.id) {
      showToast('error', 'Nenhuma planilha pronta para ativação.');
      return;
    }
    const button = document.getElementById('spreadsheet-activate-button');
    const mapping = {};
    document.querySelectorAll('[data-mapping-field]').forEach((select) => {
      mapping[select.dataset.mappingField] = select.value;
    });
    setButtonLoading(button, 'Ativando...', true);
    try {
      const response = await fetch('/agent-settings/spreadsheet/activate', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ upload_id: state.latestUpload.id, mapping }),
      });
      const data = await response.json();
      if (!response.ok || data.ok === false) throw new Error(data.message || 'Falha ao ativar a planilha.');
      renderSpreadsheet(data.upload);
      showToast('success', 'Planilha ativa para consulta.');
    } catch (error) {
      showToast('error', String(error.message || error));
    } finally {
      setButtonLoading(button, 'Ativando...', false);
    }
  }

  async function deleteSpreadsheet() {
    if (!state.latestUpload?.id) {
      showToast('error', 'Nenhuma planilha para excluir.');
      return;
    }
    const button = document.getElementById('spreadsheet-delete-button');
    setButtonLoading(button, 'Excluindo...', true);
    try {
      const response = await fetch('/agent-settings/spreadsheet/delete', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ upload_id: state.latestUpload.id }),
      });
      const data = await response.json();
      if (!response.ok || data.ok === false) throw new Error(data.message || 'Falha ao excluir a planilha.');
      renderSpreadsheet(data.latest_upload || data.active_upload || null);
      showToast('success', 'Planilha excluída.');
    } catch (error) {
      showToast('error', String(error.message || error));
    } finally {
      setButtonLoading(button, 'Excluindo...', false);
    }
  }

  async function testDatabase() {
    const button = document.getElementById('database-test-button');
    const output = document.getElementById('database-test-result');
    setButtonLoading(button, 'Testando...', true);
    try {
      const response = await fetch('/agent-settings/database/test', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payloadForTab('database')),
      });
      const data = await response.json();
      output.textContent = data.message || (data.ok ? 'Conexão validada.' : 'Não foi possível validar a fonte.');
      output.className = `mt-4 text-sm ${data.ok ? 'text-green-700' : 'text-amber-700'}`;
      if (!response.ok || data.ok === false) throw new Error(data.message || 'Falha ao validar a conexão.');
      showToast('success', data.message || 'Conexão validada.');
    } catch (error) {
      showToast('error', String(error.message || error));
    } finally {
      setButtonLoading(button, 'Testando...', false);
    }
  }

  async function runSimulator() {
    const button = document.getElementById('agent-simulator-button');
    const prompt = document.getElementById('simulator-prompt');
    const customerMessage = prompt?.value?.trim();
    if (!customerMessage) {
      showToast('error', 'Digite uma mensagem para simular.');
      return;
    }
    setButtonLoading(button, 'Simulando...', true);
    try {
      const response = await fetch('/agent-settings/test', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          customer_message: customerMessage,
          model: document.getElementById('simulator-model')?.value,
          conversation_history: state.simulatorHistory,
          ai_consecutive_replies: state.simulatorAiReplies,
        }),
      });
      const data = await response.json();
      if (!response.ok || data.ok === false) throw new Error(data.message || 'Falha ao simular o agente.');
      const badge = document.getElementById('simulator-result-badge');
      const meta = document.getElementById('simulator-result-meta');
      const text = document.getElementById('simulator-result-text');
      badge.className = `status-badge ${data.action === 'handoff' ? 'status-badge--warn' : 'status-badge--success'}`;
      badge.textContent = data.action === 'handoff' ? 'Handoff' : 'Resposta';
      meta.textContent = `Fonte: ${data.source || 'none'} · Confiança: ${data.confidence ?? '-'} · Tempo: ${data.elapsed_ms ?? 0} ms${data.matched_product?.name ? ` · Produto: ${data.matched_product.name}` : ''}`;
      text.textContent = data.preview_text || '(sem conteúdo)';

      state.simulatorHistory.push({ role: 'user', text: customerMessage });
      if (data.preview_text) {
        state.simulatorHistory.push({ role: 'assistant', text: data.preview_text });
      }
      if (data.action === 'reply' && data.preview_text) {
        state.simulatorAiReplies += 1;
      } else if (data.action === 'handoff') {
        state.simulatorAiReplies = 0;
      }
      renderSimulatorHistory();
      if (prompt) prompt.value = '';
    } catch (error) {
      showToast('error', String(error.message || error));
    } finally {
      setButtonLoading(button, 'Simulando...', false);
    }
  }

  tabButtons.forEach((button) => button.addEventListener('click', () => activateTab(button.dataset.tab)));
  saveButtons.forEach((button) =>
    button.addEventListener('click', () => {
      saveTab(button.dataset.saveTab, button);
    })
  );
  document.getElementById('run-inbound-test')?.addEventListener('click', runInboundTest);
  document.getElementById('spreadsheet-upload-button')?.addEventListener('click', uploadSpreadsheet);
  document.getElementById('spreadsheet-activate-button')?.addEventListener('click', activateSpreadsheet);
  document.getElementById('spreadsheet-delete-button')?.addEventListener('click', deleteSpreadsheet);
  document.getElementById('database-test-button')?.addEventListener('click', testDatabase);
  document.getElementById('agent-simulator-button')?.addEventListener('click', runSimulator);
  document.getElementById('agent-simulator-reset-button')?.addEventListener('click', resetSimulator);
  document.getElementById('priority-list')?.addEventListener('click', (event) => {
    const up = event.target.closest('[data-priority-up]');
    const down = event.target.closest('[data-priority-down]');
    const key = up?.dataset.priorityUp || down?.dataset.priorityDown;
    if (!key) return;
    const index = state.priority.indexOf(key);
    const nextIndex = up ? index - 1 : index + 1;
    if (index < 0 || nextIndex < 0 || nextIndex >= state.priority.length) return;
    const copy = state.priority.slice();
    [copy[index], copy[nextIndex]] = [copy[nextIndex], copy[index]];
    state.priority = copy;
    renderPriority();
    renderSummary();
  });

  activateTab('inbound');
  renderSimulatorHistory();
  loadConfig(true);
})();
