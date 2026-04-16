(function () {
  const page = document.querySelector('[data-ops-page="index"]');
  if (!page) return;

  const summary = document.getElementById('bridge-summary');
  const detail = document.getElementById('bridge-detail');
  const badge = document.getElementById('bridge-badge');
  const inboundAiSummary = document.getElementById('inbound-ai-summary');
  const inboundAiBadge = document.getElementById('inbound-ai-badge');
  const inboundAiToggleButton = document.getElementById('inbound-ai-toggle');
  const inboundAiModelSelect = document.getElementById('inbound-ai-model');
  const inboundAiModelSaveButton = document.getElementById('inbound-ai-model-save');
  const inboundAiModelTestSelect = document.getElementById('inbound-ai-model-test');
  const inboundAiTestPrompt = document.getElementById('inbound-ai-test-prompt');
  const inboundAiTestRunButton = document.getElementById('inbound-ai-test-run');
  const inboundAiTestResult = document.getElementById('inbound-ai-test-result');
  const inboundAiTestResultBadge = document.getElementById('inbound-ai-test-result-badge');
  const inboundAiTestResultMeta = document.getElementById('inbound-ai-test-result-meta');
  const inboundAiTestResultText = document.getElementById('inbound-ai-test-result-text');
  const pollingLabel = document.getElementById('bridge-polling');
  const qrWrap = document.getElementById('qr-wrap');
  const qrImage = document.getElementById('qr-image');
  const confirmModal = document.getElementById('bridge-confirm-modal');
  const confirmTitle = document.getElementById('bridge-confirm-title');
  const confirmMessage = document.getElementById('bridge-confirm-message');
  const confirmSubmit = document.getElementById('bridge-confirm-submit');
  const confirmCancel = document.getElementById('bridge-confirm-cancel');
  const toastRegion = document.getElementById('toast-region');
  const campaignsGrid = document.getElementById('campaigns-grid');
  const campaignsEmptyState = document.getElementById('campaigns-empty-state');
  const conversationsList = document.getElementById('conversations-list');
  const conversationsEmptyState = document.getElementById('conversations-empty-state');
  const conversationsRefreshButton = document.getElementById('conversations-refresh');
  const conversationDetailEmpty = document.getElementById('conversation-detail-empty');
  const conversationDetailPanel = document.getElementById('conversation-detail-panel');
  const conversationDetailBadge = document.getElementById('conversation-detail-badge');
  const conversationDetailPhone = document.getElementById('conversation-detail-phone');
  const conversationDetailMeta = document.getElementById('conversation-detail-meta');
  const conversationHistory = document.getElementById('conversation-history');
  const handoffConversationButton = document.getElementById('conversation-action-handoff');
  const closeConversationButton = document.getElementById('conversation-action-close');
  const reopenConversationButton = document.getElementById('conversation-action-reopen');

  const refreshButton = document.getElementById('bridge-refresh');
  const qrButton = document.getElementById('bridge-load-qr');
  const restartButton = document.getElementById('bridge-restart');
  const allButtons = [refreshButton, qrButton, restartButton].filter(Boolean);

  let bridgeState = {
    connected: false,
    state: 'unknown',
  };
  let inboundAiEnabled = true;
  let selectedAiModel = '';
  let availableAiModels = [];
  let selectedAiTestModel = '';
  let qrPolling = null;
  let confirmHandler = null;
  let selectedConversationId = null;
  let conversationsState = [];

  function redirectToLogin() {
    window.location.assign('/login');
  }

  function showToast(type, message) {
    const item = document.createElement('div');
    item.className = `toast toast--${type}`;
    item.innerHTML = `<div><p class="font-medium text-ink">${message}</p></div>`;
    toastRegion?.appendChild(item);
    window.setTimeout(() => item.remove(), 3600);
  }

  function setButtonsDisabled(disabled) {
    allButtons.forEach((button) => {
      if (button) button.disabled = disabled;
    });
  }

  function setButtonLoading(button, loadingLabel, active) {
    if (!button) return;
    if (active) {
      if (!button.dataset.originalLabel) button.dataset.originalLabel = button.textContent || '';
      button.disabled = true;
      button.innerHTML = `<span class="button-spinner" aria-hidden="true"></span><span>${loadingLabel}</span>`;
      return;
    }
    if (button.dataset.originalLabel) {
      button.textContent = button.dataset.originalLabel;
    }
    button.disabled = false;
  }

  function setBadge(tone, label) {
    badge.className = `status-badge status-badge--${tone}`;
    badge.textContent = label;
  }

  function renderInboundAiControl(enabled) {
    inboundAiEnabled = Boolean(enabled);
    if (!inboundAiBadge || !inboundAiSummary || !inboundAiToggleButton) return;
    if (inboundAiEnabled) {
      inboundAiBadge.className = 'status-badge status-badge--success';
      inboundAiBadge.textContent = 'Ativa';
      inboundAiSummary.textContent = 'A IA responde mensagens inbound automaticamente.';
      inboundAiToggleButton.textContent = 'Desativar IA';
      inboundAiToggleButton.className = 'danger-button';
      renderConversations(conversationsState);
      return;
    }
    inboundAiBadge.className = 'status-badge status-badge--warn';
    inboundAiBadge.textContent = 'Desativada';
    inboundAiSummary.textContent = 'Mensagens inbound ficam registradas, mas sem resposta automatica.';
    inboundAiToggleButton.textContent = 'Ativar IA';
    inboundAiToggleButton.className = 'primary-button';
    renderConversations(conversationsState);
  }

  function renderInboundAiModels(models, selectedModel) {
    availableAiModels = Array.isArray(models) ? models : [];
    selectedAiModel = String(selectedModel || '').trim();
    if (!inboundAiModelSelect || !inboundAiModelSaveButton || !inboundAiModelTestSelect || !inboundAiTestRunButton) return;

    inboundAiModelSelect.innerHTML = '';
    inboundAiModelTestSelect.innerHTML = '';
    if (!availableAiModels.length) {
      const option = document.createElement('option');
      option.value = '';
      option.textContent = 'Nenhum modelo configurado em OPENROUTER_MODELS';
      inboundAiModelSelect.appendChild(option);
      inboundAiModelTestSelect.appendChild(option.cloneNode(true));
      inboundAiModelSelect.disabled = true;
      inboundAiModelSaveButton.disabled = true;
      inboundAiModelTestSelect.disabled = true;
      inboundAiTestRunButton.disabled = true;
      return;
    }

    availableAiModels.forEach((model) => {
      const option = document.createElement('option');
      option.value = model;
      option.textContent = model;
      inboundAiModelSelect.appendChild(option);
      inboundAiModelTestSelect.appendChild(option.cloneNode(true));
    });
    const normalizedSelected = availableAiModels.find((model) => model === selectedAiModel) || availableAiModels[0];
    inboundAiModelSelect.value = normalizedSelected;
    selectedAiModel = normalizedSelected;
    inboundAiModelSelect.disabled = false;
    inboundAiModelSaveButton.disabled = false;
    selectedAiTestModel = availableAiModels.find((model) => model === selectedAiTestModel) || normalizedSelected;
    inboundAiModelTestSelect.value = selectedAiTestModel;
    inboundAiModelTestSelect.disabled = false;
    inboundAiTestRunButton.disabled = false;
  }

  function renderInboundAiTestResult(payload, errorMessage = '') {
    if (!inboundAiTestResult || !inboundAiTestResultBadge || !inboundAiTestResultMeta || !inboundAiTestResultText) return;
    inboundAiTestResult.classList.remove('hidden');

    if (errorMessage) {
      inboundAiTestResultBadge.className = 'status-badge status-badge--error';
      inboundAiTestResultBadge.textContent = 'Falha';
      inboundAiTestResultMeta.textContent = errorMessage;
      inboundAiTestResultText.textContent = '';
      return;
    }

    const action = String(payload.action || '').trim();
    const tone = action === 'handoff' ? 'warn' : action === 'raw_text' ? 'info' : 'success';
    const label = action === 'handoff' ? 'Handoff' : action === 'raw_text' ? 'Texto bruto' : 'Resposta';
    inboundAiTestResultBadge.className = `status-badge status-badge--${tone}`;
    inboundAiTestResultBadge.textContent = label;
    const warning = String(payload.warning || '').trim();
    inboundAiTestResultMeta.textContent = `Modelo: ${payload.model || '-'} · Confianca: ${payload.confidence ?? '-'}${warning ? ` · ${warning}` : ''}`;
    inboundAiTestResultText.textContent = payload.preview_text || '(sem conteudo)';
  }

  function conversationTone(status) {
    if (status === 'ai_active') {
      if (!inboundAiEnabled) return { tone: 'warn', label: 'IA desativada' };
      return { tone: 'success', label: 'IA ativa' };
    }
    if (status === 'waiting_human') return { tone: 'warn', label: 'Aguardando humano' };
    if (status === 'closed') return { tone: 'info', label: 'Encerrada' };
    return { tone: 'info', label: status || 'Desconhecido' };
  }

  function normalizeUtcDateInput(value) {
    const raw = String(value || '').trim();
    if (!raw) return '';
    if (raw.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(raw)) {
      return raw;
    }
    if (raw.includes('T')) {
      return `${raw}Z`;
    }
    return `${raw.replace(' ', 'T')}Z`;
  }

  function formatDateTime(value) {
    const normalized = normalizeUtcDateInput(value);
    if (!normalized) return '-';
    const parsed = new Date(normalized);
    if (Number.isNaN(parsed.getTime())) return String(value || '-');
    return new Intl.DateTimeFormat('pt-BR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }).format(parsed);
  }

  function describeSession(session) {
    if (session.connected) {
      const phone = session.phone ? `Numero conectado e pronto para envio (${session.phone}).` : 'Numero conectado e pronto para envio.';
      return {
        tone: 'success',
        badge: 'Conectado',
        summary: phone,
        detail: 'O canal esta liberado para teste e disparo real.',
      };
    }

    if (session.state === 'initialize_failed') {
      return {
        tone: 'error',
        badge: 'Falha',
        summary: 'Sessao com falha de inicializacao.',
        detail: 'Troque o numero ou atualize o status para iniciar uma nova tentativa de conexao.',
      };
    }

    if (session.hasQr || session.state === 'qr_ready') {
      return {
        tone: 'warn',
        badge: 'Aguardando QR',
        summary: 'Sessao pronta para conectar um numero.',
        detail: 'Gere o QR, escaneie com o WhatsApp e aguarde a confirmacao no painel.',
      };
    }

    return {
      tone: 'warn',
      badge: 'Desconectado',
      summary: 'Sessao desconectada.',
      detail: 'Gere um novo QR para conectar o numero de envio antes de operar as campanhas.',
    };
  }

  function renderSession(session) {
    bridgeState = session;
    const view = describeSession(session);
    setBadge(view.tone, view.badge);
    summary.textContent = view.summary;
    detail.textContent = view.detail;
  }

  async function refreshSession(showErrors = false) {
    pollingLabel?.classList.remove('opacity-40');
    pollingLabel?.setAttribute('data-polling-state', 'running');

    try {
      const response = await fetch('/bridge/session');
      if (response.status === 401) {
        redirectToLogin();
        return;
      }
      const data = await response.json();
      if (!response.ok || !data.ok) {
        throw new Error(data.message || 'Falha ao consultar sessao');
      }
      renderSession(data.session);
    } catch (error) {
      setBadge('error', 'Erro');
      summary.textContent = 'Nao foi possivel atualizar o estado do WhatsApp.';
      detail.textContent = String(error.message || error);
      if (showErrors) showToast('error', 'Falha ao consultar o status do WhatsApp.');
    } finally {
      pollingLabel?.setAttribute('data-polling-state', 'idle');
      pollingLabel?.classList.add('opacity-40');
    }
  }

  async function loadInboundAiControl(showErrors = false) {
    try {
      const response = await fetch('/inbound/ai-control');
      if (response.status === 401) {
        redirectToLogin();
        return;
      }
      const data = await response.json();
      if (!response.ok || data.ok === false) {
        throw new Error(data.message || 'Falha ao carregar estado da IA.');
      }
      renderInboundAiControl(Boolean(data.enabled));
      renderInboundAiModels(data.available_models || [], data.selected_model || '');
    } catch (error) {
      if (showErrors) showToast('error', String(error.message || error));
    }
  }

  async function toggleInboundAiControl() {
    if (!inboundAiToggleButton) return;
    setButtonLoading(inboundAiToggleButton, 'Salvando...', true);
    let shouldRerender = false;
    try {
      const response = await fetch('/inbound/ai-control', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ enabled: !inboundAiEnabled }),
      });
      if (response.status === 401) {
        redirectToLogin();
        return;
      }
      const data = await response.json();
      if (!response.ok || data.ok === false) {
        throw new Error(data.message || 'Falha ao atualizar estado da IA.');
      }
      renderInboundAiControl(Boolean(data.enabled));
      shouldRerender = true;
      showToast('success', data.enabled ? 'IA inbound ativada.' : 'IA inbound desativada.');
    } catch (error) {
      showToast('error', String(error.message || error));
    } finally {
      setButtonLoading(inboundAiToggleButton, 'Salvando...', false);
      if (shouldRerender) {
        renderInboundAiControl(inboundAiEnabled);
      }
    }
  }

  async function saveInboundAiModel() {
    if (!inboundAiModelSelect || !inboundAiModelSaveButton) return;
    const model = String(inboundAiModelSelect.value || '').trim();
    if (!model) {
      showToast('error', 'Selecione um modelo válido.');
      return;
    }
    setButtonLoading(inboundAiModelSaveButton, 'Salvando...', true);
    try {
      const response = await fetch('/inbound/ai-model', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ model }),
      });
      if (response.status === 401) {
        redirectToLogin();
        return;
      }
      const data = await response.json();
      if (!response.ok || data.ok === false) {
        throw new Error(data.message || 'Falha ao salvar modelo.');
      }
      selectedAiModel = String(data.selected_model || model);
      inboundAiModelSelect.value = selectedAiModel;
      showToast('success', `Modelo ativo: ${selectedAiModel}`);
    } catch (error) {
      showToast('error', String(error.message || error));
    } finally {
      setButtonLoading(inboundAiModelSaveButton, 'Salvando...', false);
    }
  }

  async function runInboundAiModelTest() {
    if (!inboundAiModelTestSelect || !inboundAiTestPrompt || !inboundAiTestRunButton) return;
    const model = String(inboundAiModelTestSelect.value || '').trim();
    const prompt = String(inboundAiTestPrompt.value || '').trim();
    if (!model) {
      showToast('error', 'Selecione um modelo para teste.');
      return;
    }
    if (!prompt) {
      showToast('error', 'Digite uma mensagem para testar.');
      return;
    }

    setButtonLoading(inboundAiTestRunButton, 'Testando...', true);
    try {
      const response = await fetch('/inbound/ai-model/test', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ model, prompt }),
      });
      if (response.status === 401) {
        redirectToLogin();
        return;
      }
      const data = await response.json();
      if (!response.ok || data.ok === false) {
        throw new Error(data.message || 'Falha ao testar modelo.');
      }
      selectedAiTestModel = model;
      renderInboundAiTestResult(data);
    } catch (error) {
      renderInboundAiTestResult(null, String(error.message || error));
      showToast('error', String(error.message || error));
    } finally {
      setButtonLoading(inboundAiTestRunButton, 'Testando...', false);
    }
  }

  function openConfirm(config) {
    confirmTitle.textContent = config.title;
    confirmMessage.textContent = config.message;
    confirmHandler = config.onConfirm;
    confirmModal?.showModal();
  }

  async function loadQr() {
    setButtonLoading(qrButton, 'Gerando QR...', true);
    qrWrap?.classList.remove('hidden');
    qrImage?.classList.add('hidden');
    qrImage?.removeAttribute('src');

    if (qrPolling) {
      window.clearInterval(qrPolling);
      qrPolling = null;
    }

    let attempts = 0;
    const maxAttempts = 10;

    const fetchQr = async () => {
      attempts += 1;
      try {
        const response = await fetch('/bridge/qr');
        const data = await response.json();
        if (response.ok && data.ok && data.qr?.base64) {
          qrImage.src = data.qr.base64;
          qrImage.classList.remove('hidden');
          await refreshSession();
          showToast('success', 'QR atualizado. Escaneie para concluir a conexao.');
          if (qrPolling) {
            window.clearInterval(qrPolling);
            qrPolling = null;
          }
          setButtonLoading(qrButton, 'Gerando QR...', false);
          return;
        }
      } catch (error) {
        if (attempts >= maxAttempts) {
          showToast('error', 'Nao foi possivel gerar o QR agora.');
        }
      }

      if (attempts >= maxAttempts) {
        if (qrPolling) {
          window.clearInterval(qrPolling);
          qrPolling = null;
        }
        setButtonLoading(qrButton, 'Gerando QR...', false);
      }
    };

    await fetchQr();
    if (!qrImage?.getAttribute('src')) {
      qrPolling = window.setInterval(fetchQr, 1500);
    }
  }

  async function restartSession() {
    setButtonsDisabled(true);
    setButtonLoading(restartButton, 'Trocando numero...', true);
    try {
      const response = await fetch('/bridge/reset', { method: 'POST' });
      if (response.status === 401) {
        redirectToLogin();
        return;
      }
      const data = await response.json();
      if (!response.ok || !data.ok) {
        throw new Error(data.message || 'Falha ao trocar numero');
      }
      showToast('success', 'Numero desconectado. Gere um novo QR para continuar.');
      renderSession({
        connected: false,
        state: 'qr_ready',
        phone: null,
        hasQr: true,
        lastError: null,
        history: [],
      });
      await loadQr();
    } catch (error) {
      showToast('error', 'Nao foi possivel trocar o numero agora.');
    } finally {
      setButtonLoading(restartButton, 'Trocando numero...', false);
      setButtonsDisabled(false);
      confirmModal?.close();
    }
  }

  async function deleteCampaign(button) {
    const campaignId = button?.dataset.campaignId;
    if (!campaignId) return;

    setButtonLoading(button, 'Excluindo...', true);
    try {
      const response = await fetch(`/campaigns/${campaignId}/delete`, { method: 'POST' });
      if (response.status === 401) {
        redirectToLogin();
        return;
      }
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.ok === false) {
        throw new Error(data.message || 'Nao foi possivel excluir a campanha.');
      }

      const card = button.closest('[data-campaign-card]');
      card?.remove();
      if (campaignsGrid && campaignsEmptyState && !campaignsGrid.querySelector('[data-campaign-card]')) {
        campaignsGrid.classList.add('hidden');
        campaignsEmptyState.classList.remove('hidden');
      }
      showToast('success', data.message || 'Campanha excluida com sucesso.');
      confirmModal?.close();
    } catch (error) {
      showToast('error', String(error.message || error));
      setButtonLoading(button, 'Excluindo...', false);
    }
  }

  function renderConversations(items) {
    conversationsState = items || [];
    if (!conversationsList) return;
    conversationsList.innerHTML = '';

    if (!conversationsState.length) {
      conversationsEmptyState?.classList.remove('hidden');
      return;
    }

    conversationsEmptyState?.classList.add('hidden');
    conversationsState.forEach((item) => {
      const tone = conversationTone(item.status);
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `conversation-item${selectedConversationId === item.id ? ' is-active' : ''}`;
      button.dataset.conversationId = String(item.id);
      button.innerHTML = `
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="text-sm font-semibold text-ink">${item.customer_phone || 'Sem telefone'}</p>
            <p class="mt-1 text-xs text-muted">Respostas IA: ${item.ai_consecutive_replies || 0}</p>
          </div>
          <span class="status-badge status-badge--${tone.tone}">${tone.label}</span>
        </div>
      `;
      conversationsList.appendChild(button);
    });
  }

  function renderConversationDetail(payload) {
    const item = payload?.item;
    if (!item) return;

    const tone = conversationTone(item.status);
    selectedConversationId = item.id;
    conversationDetailEmpty?.classList.add('hidden');
    conversationDetailPanel?.classList.remove('hidden');
    conversationDetailBadge.className = `status-badge status-badge--${tone.tone}`;
    conversationDetailBadge.textContent = tone.label;
    conversationDetailPhone.textContent = item.customer_phone || '-';
    conversationDetailMeta.textContent = `Respostas IA consecutivas: ${item.ai_consecutive_replies || 0}${item.handoff_target_phone ? ` · Humano: ${item.handoff_target_phone}` : ''}`;
    conversationHistory.innerHTML = '';

    (payload.messages || []).forEach((message) => {
      const card = document.createElement('article');
      card.className = 'conversation-history-item';
      card.dataset.direction = message.direction || '';
      card.innerHTML = `
        <div class="flex items-center justify-between gap-3">
          <p class="text-xs font-medium text-muted">${message.sender_type || message.direction || 'mensagem'}</p>
          <p class="text-xs text-muted">${formatDateTime(message.created_at)}</p>
        </div>
        <p class="conversation-history-text mt-2 text-sm text-ink"></p>
      `;
      card.querySelector('.conversation-history-text').textContent = message.message_text || '';
      conversationHistory.appendChild(card);
    });

    renderConversations(conversationsState);
  }

  async function loadConversations(showErrors = false) {
    try {
      const response = await fetch('/conversations');
      if (response.status === 401) {
        redirectToLogin();
        return;
      }
      const data = await response.json();
      renderConversations(data.items || []);
      if (selectedConversationId) {
        const exists = (data.items || []).some((item) => item.id === selectedConversationId);
        if (!exists) {
          selectedConversationId = null;
          conversationDetailPanel?.classList.add('hidden');
          conversationDetailEmpty?.classList.remove('hidden');
        }
      }
    } catch (error) {
      if (showErrors) showToast('error', 'Nao foi possivel carregar as conversas.');
    }
  }

  async function loadConversationDetail(conversationId, showErrors = false) {
    try {
      const response = await fetch(`/conversations/${conversationId}`);
      if (response.status === 401) {
        redirectToLogin();
        return;
      }
      if (!response.ok) {
        throw new Error('Falha ao carregar conversa.');
      }
      const data = await response.json();
      renderConversationDetail(data);
    } catch (error) {
      if (showErrors) showToast('error', String(error.message || error));
    }
  }

  async function runConversationAction(url, message) {
    if (!selectedConversationId) return;
    try {
      const response = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ reason: 'manual_review' }) });
      if (response.status === 401) {
        redirectToLogin();
        return;
      }
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.ok === false) {
        throw new Error(data.message || 'Falha ao atualizar a conversa.');
      }
      showToast('success', message);
      await loadConversations(false);
      await loadConversationDetail(selectedConversationId, false);
    } catch (error) {
      showToast('error', String(error.message || error));
    }
  }

  refreshButton?.addEventListener('click', async () => {
    setButtonLoading(refreshButton, 'Atualizando...', true);
    await refreshSession(true);
    setButtonLoading(refreshButton, 'Atualizando...', false);
  });

  qrButton?.addEventListener('click', loadQr);

  restartButton?.addEventListener('click', () => {
    openConfirm({
      title: 'Trocar numero do WhatsApp',
      message: 'A sessao atual sera desconectada. O envio so volta a ficar disponivel depois da nova leitura do QR.',
      onConfirm: restartSession,
    });
  });

  inboundAiToggleButton?.addEventListener('click', async () => {
    await toggleInboundAiControl();
  });

  inboundAiModelSaveButton?.addEventListener('click', async () => {
    await saveInboundAiModel();
  });

  inboundAiModelTestSelect?.addEventListener('change', () => {
    selectedAiTestModel = String(inboundAiModelTestSelect.value || '').trim();
  });

  inboundAiTestRunButton?.addEventListener('click', async () => {
    await runInboundAiModelTest();
  });

  campaignsGrid?.addEventListener('click', (event) => {
    const target = event.target.closest('[data-home-action="delete-campaign"]');
    if (!target) return;
    event.preventDefault();
    event.stopPropagation();
    const campaignName = target.dataset.campaignName || 'esta campanha';
    openConfirm({
      title: 'Excluir campanha',
      message: `A campanha "${campaignName}" sera removida permanentemente, junto com contatos e historico operacional.`,
      onConfirm: async () => {
        await deleteCampaign(target);
      },
    });
  });

  conversationsList?.addEventListener('click', (event) => {
    const target = event.target.closest('[data-conversation-id]');
    if (!target) return;
    const conversationId = Number(target.dataset.conversationId || 0);
    if (!conversationId) return;
    loadConversationDetail(conversationId, true);
  });

  conversationsRefreshButton?.addEventListener('click', async () => {
    setButtonLoading(conversationsRefreshButton, 'Atualizando...', true);
    await loadConversations(true);
    if (selectedConversationId) {
      await loadConversationDetail(selectedConversationId, false);
    }
    setButtonLoading(conversationsRefreshButton, 'Atualizando...', false);
  });

  handoffConversationButton?.addEventListener('click', async () => {
    await runConversationAction(`/conversations/${selectedConversationId}/handoff`, 'Conversa encaminhada para humano.');
  });

  closeConversationButton?.addEventListener('click', async () => {
    await runConversationAction(`/conversations/${selectedConversationId}/close`, 'Conversa encerrada.');
  });

  reopenConversationButton?.addEventListener('click', async () => {
    await runConversationAction(`/conversations/${selectedConversationId}/reopen-ai`, 'Conversa reaberta para IA.');
  });

  confirmSubmit?.addEventListener('click', async () => {
    if (confirmHandler) await confirmHandler();
  });

  confirmCancel?.addEventListener('click', () => {
    confirmModal?.close();
  });

  refreshSession();
  loadInboundAiControl(false);
  loadConversations(false);
  window.setInterval(() => refreshSession(false), 5000);
  window.setInterval(() => {
    loadConversations(false);
    if (selectedConversationId) loadConversationDetail(selectedConversationId, false);
  }, 8000);
})();
