(function () {
  const page = document.querySelector('[data-ops-page="index"]');
  if (!page) return;

  const summary = document.getElementById('bridge-summary');
  const detail = document.getElementById('bridge-detail');
  const badge = document.getElementById('bridge-badge');
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

  const refreshButton = document.getElementById('bridge-refresh');
  const qrButton = document.getElementById('bridge-load-qr');
  const restartButton = document.getElementById('bridge-restart');
  const allButtons = [refreshButton, qrButton, restartButton].filter(Boolean);

  let bridgeState = {
    connected: false,
    state: 'unknown',
  };
  let qrPolling = null;
  let confirmHandler = null;

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

  confirmSubmit?.addEventListener('click', async () => {
    if (confirmHandler) await confirmHandler();
  });

  confirmCancel?.addEventListener('click', () => {
    confirmModal?.close();
  });

  refreshSession();
  window.setInterval(() => refreshSession(false), 5000);
})();
