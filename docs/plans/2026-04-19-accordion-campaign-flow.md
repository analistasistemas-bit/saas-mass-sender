# Accordion Campaign Flow — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Substituir a tela de campanha (que exibe todos os formulários de uma vez) por um accordion de 6 passos guiados, mantendo toda a lógica JS existente intacta.

**Architecture:** O JS já possui `getStepperState()` que retorna `['done'|'active'|'blocked']` para 6 passos. O `renderStepper()` aplica `data-step-state` nos itens. A mudança é: (1) substituir os `.stepper-item` por `.accordion-step` com corpo colapsável; (2) adicionar uma barra compacta de stats sempre visível; (3) manter o card "Ação atual" persistente acima do accordion (sem mover `#primary-action-button`). Os formulários/conteúdo de cada passo ficam no `accordion-step__body`.

**Tech Stack:** Jinja2, Tailwind CSS (CDN), CSS custom properties, vanilla JS (sem framework)

---

## Task 1: CSS — Componentes de accordion em `static/styles.css`

**Files:**
- Modify: `static/styles.css`

### Step 1: Adicionar classes de accordion ao final do arquivo

Abrir `static/styles.css` e adicionar ao final:

```css
/* ── Accordion Steps ───────────────────────────────────────────── */
.accordion-step {
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  background: var(--bg-surface);
  overflow: hidden;
  transition: border-color 0.15s ease;
}

.accordion-step + .accordion-step {
  margin-top: 8px;
}

.accordion-step__header {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 14px 20px;
  background: transparent;
  border: none;
  cursor: pointer;
  text-align: left;
  transition: background 0.1s ease;
}

.accordion-step__header:hover:not([disabled]) {
  background: var(--bg-press);
}

.accordion-step__number {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  flex-shrink: 0;
  background: var(--bg-elevated);
  color: var(--text-subdued);
  border: 1px solid var(--border-subtle);
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}

.accordion-step__label {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-subdued);
  flex: 1;
  transition: color 0.15s;
}

.accordion-step__status {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-subdued);
  margin-left: auto;
}

.accordion-step__chevron {
  width: 16px;
  height: 16px;
  color: var(--text-subdued);
  transition: transform 0.2s ease;
  flex-shrink: 0;
}

.accordion-step__body {
  display: none;
  padding: 0 20px 20px;
  border-top: 1px solid var(--border-subtle);
}

/* Estado: ativo (passo atual) */
.accordion-step[data-step-state="active"] {
  border-color: rgba(62, 207, 142, 0.25);
}

.accordion-step[data-step-state="active"] .accordion-step__header {
  background: rgba(62, 207, 142, 0.04);
}

.accordion-step[data-step-state="active"] .accordion-step__number {
  background: var(--brand-accent);
  color: #000;
  border-color: var(--brand-accent);
}

.accordion-step[data-step-state="active"] .accordion-step__label {
  color: var(--text-base);
}

.accordion-step[data-step-state="active"] .accordion-step__status {
  color: var(--brand-accent);
}

.accordion-step[data-step-state="active"] .accordion-step__body {
  display: block;
}

.accordion-step[data-step-state="active"] .accordion-step__chevron {
  transform: rotate(180deg);
}

/* Estado: concluído */
.accordion-step[data-step-state="done"] .accordion-step__number {
  background: rgba(62, 207, 142, 0.15);
  color: var(--brand-accent);
  border-color: rgba(62, 207, 142, 0.3);
}

.accordion-step[data-step-state="done"] .accordion-step__label {
  color: var(--text-base);
}

.accordion-step[data-step-state="done"] .accordion-step__status {
  color: var(--brand-accent);
}

/* Passo concluído expandido (ao clicar para revisar) */
.accordion-step[data-step-state="done"].is-open .accordion-step__body {
  display: block;
}

.accordion-step[data-step-state="done"].is-open .accordion-step__chevron {
  transform: rotate(180deg);
}

/* Estado: bloqueado */
.accordion-step[data-step-state="blocked"] .accordion-step__header {
  cursor: not-allowed;
  opacity: 0.45;
}

/* ── Compact Stats Strip ────────────────────────────────────────── */
.stats-strip-top {
  display: flex;
  align-items: center;
  gap: 0;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--bg-surface);
  overflow: hidden;
}

.stats-strip-top__item {
  flex: 1;
  padding: 10px 16px;
  border-right: 1px solid var(--border-subtle);
  min-width: 0;
}

.stats-strip-top__item:last-child {
  border-right: none;
}

.stats-strip-top__label {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-subdued);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.stats-strip-top__value {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-base);
  line-height: 1.2;
  margin-top: 2px;
}

/* ── Progress bar dentro da strip ───────────────────────────────── */
.progress-strip {
  flex: 2;
  padding: 10px 16px;
  border-right: 1px solid var(--border-subtle);
}

.progress-strip__top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 5px;
}

.progress-strip__label {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-subdued);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
```

### Step 2: Verificar visualmente

Não há como verificar CSS isolado. Seguir para Task 2.

---

## Task 2: HTML — Reestruturar `templates/campaign.html`

**Files:**
- Modify: `templates/campaign.html`

Esta é a tarefa principal. O HTML atual tem:
1. Header (voltar + excluir)
2. Section: nome + stepper + service health + narrative
3. Grid 2 colunas: "Próxima ação" + "Acompanhamento"
4. Grid 2 colunas: "Mensagem e validação" + Tabela de contatos
5. Section: Resultados
6. Section: Atividade/Logs

A nova estrutura será:
1. Header (voltar + excluir) — **inalterado**
2. Card do cabeçalho: nome + badges + narrative + last-updated — compactado
3. Barra de stats sempre visível: Enviados | Falhas | Pendentes | ETA | Progress
4. Card "Ação atual": primary-action-button + secondary + destructive + insight — **sem mudança de IDs**
5. 6 accordion steps com os formulários/conteúdo
6. Section: Atividade/Logs — **inalterado**
7. Section: Resultados — **inalterado**
8. Floating elements (execution bar, modal, toast) — **inalterados**

### Step 1: Substituir a `<section>` do cabeçalho (linhas ~62–114)

**Remover** todo o bloco `<section class="rounded-xl border border-line bg-surface p-6">` que contém o stepper + service health, e **substituir** por:

```html
<section class="rounded-xl border border-line bg-surface p-5">
  <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
    <div class="space-y-2">
      <div class="flex flex-wrap items-center gap-2">
        <h1 class="text-2xl font-bold tracking-tight text-ink">{{ campaign.name }}</h1>
        <span id="campaign-status-badge" class="status-badge" data-state="{{ campaign.status }}">{{ STATUS_PT.get(campaign.status, campaign.status) }}</span>
        <span id="bridge-state-badge" class="status-badge status-badge--muted">Verificando WhatsApp</span>
      </div>
      <p id="status-narrative" data-testid="status-narrative" class="max-w-2xl text-sm text-muted">
        Carregando estado operacional da campanha.
      </p>
    </div>
    <div class="rounded-lg border border-line bg-press px-3 py-2">
      <div class="flex items-center gap-1.5 text-xs font-medium text-muted">
        <span class="pulse-dot"></span>
        <span id="polling-label">Atualizando...</span>
      </div>
      <p id="last-updated" class="mt-0.5 text-xs text-muted">Atualizacao inicial em andamento.</p>
    </div>
  </div>
</section>
```

### Step 2: Adicionar barra de stats compacta

Logo após a section do cabeçalho, adicionar:

```html
<div class="stats-strip-top">
  <div class="progress-strip">
    <div class="progress-strip__top">
      <span class="progress-strip__label">Progresso</span>
      <span id="progress-caption" class="text-xs font-semibold text-muted">0%</span>
    </div>
    <div class="overflow-hidden rounded-full bg-elevated">
      <div id="progress-fill" class="progress-fill h-1.5 rounded-full" style="width: 0%"></div>
    </div>
  </div>
  <div class="stats-strip-top__item">
    <p class="stats-strip-top__label">Enviados</p>
    <p id="sent" class="stats-strip-top__value">{{ stats.sent }}</p>
  </div>
  <div class="stats-strip-top__item">
    <p class="stats-strip-top__label">Falhas</p>
    <p id="failed" class="stats-strip-top__value text-danger">{{ stats.failed }}</p>
  </div>
  <div class="stats-strip-top__item">
    <p class="stats-strip-top__label">Pendentes</p>
    <p id="pending" class="stats-strip-top__value">{{ stats.pending }}</p>
  </div>
  <div class="stats-strip-top__item">
    <p class="stats-strip-top__label">ETA</p>
    <p id="eta-value" class="stats-strip-top__value text-sm">--</p>
  </div>
</div>
```

### Step 3: Substituir o grid "Próxima ação" + "Acompanhamento" (seção 3)

**Remover** o `<section class="grid gap-6 xl:grid-cols-[55%_1fr]">` inteiro e **substituir** por um card simples "Ação atual":

```html
<section class="rounded-xl border border-line bg-surface p-5">
  <div class="flex flex-col gap-4">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <p class="text-[13px] font-medium text-muted">Acao atual</p>
        <h2 id="primary-title" class="mt-1 text-lg font-bold text-ink">Preparando campanha</h2>
        <p id="primary-description" class="mt-1 max-w-xl text-sm text-muted">
          O sistema vai destacar apenas a proxima decisao importante.
        </p>
      </div>
      <div class="hidden rounded-lg border border-line bg-press px-3 py-2 text-sm text-muted lg:block">
        <p class="text-xs font-medium text-ink">Velocidade</p>
        <p id="speed-value" class="mt-0.5 text-xs">--</p>
        <p id="speed-note" class="text-xs text-muted">Config.: --</p>
      </div>
    </div>

    <div data-testid="primary-action" class="rounded-lg border border-brand/15 bg-brand/5 p-4">
      <div class="flex flex-col gap-3">
        <button id="primary-action-button" type="button" class="primary-button w-full justify-center">
          Carregando...
        </button>
        <div id="secondary-actions" class="flex flex-wrap gap-2"></div>
        <div id="destructive-actions" class="flex flex-wrap gap-2 border-t border-line pt-3"></div>
      </div>
    </div>

    <div id="action-insight" class="rounded-lg border border-line bg-press px-4 py-3">
      <div class="flex items-start gap-2.5">
        <div class="mt-1 h-2 w-2 shrink-0 rounded-full bg-brand"></div>
        <p id="action-insight-text" class="text-sm text-muted">
          O fluxo sera ajustado automaticamente conforme a campanha avanca.
        </p>
      </div>
    </div>
  </div>
</section>
```

**Mover** os elementos restantes do "Acompanhamento" que não estão na strip:
- `#total`, `#valid-count`, `#invalid-count`, `#runtime-profile-badge`, `#runtime-profile-copy`, `#daily-limit-summary`, `#progress-summary`, `#result-value`, `#result-note` → colocar dentro do passo 6 (accordion step 5, Enviar campanha) como "Detalhes de progresso"

### Step 4: Substituir toda a seção 4 (grid "Mensagem e validação" + contatos) pelos accordions

**Remover** o `<section class="grid gap-6 xl:grid-cols-[0.85fr_1.15fr]">` inteiro (linhas ~214–641) e **substituir** por:

```html
<div class="flex flex-col" data-testid="campaign-stepper">

  <!-- Passo 1: Conectar WhatsApp -->
  <div class="accordion-step" data-step-key="0" data-step-state="active">
    <button class="accordion-step__header" type="button" data-accordion-trigger="0">
      <span class="accordion-step__number">1</span>
      <span class="accordion-step__label">Conectar WhatsApp</span>
      <span class="accordion-step__status">Verificando...</span>
      <svg class="accordion-step__chevron" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <path d="m5 7.5 5 5 5-5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </button>
    <div class="accordion-step__body">
      <div id="service-health-layout" class="mt-4 flex flex-col gap-3">
        <div class="rounded-lg border border-line bg-press p-3">
          <div class="flex flex-wrap gap-3" id="service-status-grid">
            <article class="service-status-card">
              <p class="metric-label">Motor de envio</p>
              <span id="worker-service-badge" class="status-badge status-badge--muted">Verificando</span>
              <p id="worker-service-copy" class="mt-1.5 text-sm text-muted">Aguardando leitura do motor de envio.</p>
            </article>
            <article class="service-status-card">
              <p class="metric-label">WhatsApp / bridge</p>
              <span id="bridge-service-badge" class="status-badge status-badge--muted">Verificando</span>
              <p id="bridge-service-copy" class="mt-1.5 text-sm text-muted">Aguardando leitura do servico de WhatsApp.</p>
            </article>
          </div>
        </div>
        <div id="service-alert-panel" class="hidden rounded-lg border border-line bg-press p-3">
          <p id="service-alert-title" class="text-xs font-medium text-brand">Monitor operacional</p>
          <p id="service-alert-message" class="mt-2 text-sm text-muted">Nenhum alerta operacional ativo.</p>
        </div>
      </div>
    </div>
  </div>

  <!-- Passo 2: Preparar mensagem -->
  <div class="accordion-step" data-step-key="1" data-step-state="blocked">
    <button class="accordion-step__header" type="button" data-accordion-trigger="1">
      <span class="accordion-step__number">2</span>
      <span class="accordion-step__label">Preparar mensagem</span>
      <span class="accordion-step__status"></span>
      <svg class="accordion-step__chevron" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <path d="m5 7.5 5 5 5-5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </button>
    <div class="accordion-step__body">
      <div class="mt-4">
        <form id="template-form" method="post" action="/campaigns/{{ campaign.id }}/template" class="space-y-3">
          <label class="block space-y-1.5">
            <span class="text-sm font-medium text-muted">Mensagem da campanha</span>
            <textarea
              name="message_template"
              rows="5"
              class="w-full rounded-lg border border-line bg-surface px-3 py-2.5 text-sm leading-relaxed outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20"
            >{{ campaign.message_template }}</textarea>
          </label>
          <div class="flex flex-wrap items-center gap-2">
            <button type="submit" id="save-template-button" class="secondary-button">Salvar mensagem</button>
            <span class="rounded-md border border-line bg-press px-2.5 py-1.5 text-xs font-medium text-muted">
              Variavel: {{'{{nome}}'}}
            </span>
          </div>
        </form>
      </div>
    </div>
  </div>

  <!-- Passo 3: Importar contatos -->
  <div class="accordion-step" data-step-key="2" data-step-state="blocked">
    <button class="accordion-step__header" type="button" data-accordion-trigger="2">
      <span class="accordion-step__number">3</span>
      <span class="accordion-step__label">Importar contatos</span>
      <span class="accordion-step__status"></span>
      <svg class="accordion-step__chevron" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <path d="m5 7.5 5 5 5-5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </button>
    <div class="accordion-step__body">
      <div class="mt-4 space-y-4">
        <form id="upload-form" class="space-y-3">
          <div class="rounded-lg border border-dashed border-line bg-press p-4">
            <label class="block space-y-1.5" for="csv-file-input">
              <span class="text-sm font-medium text-muted">Arquivo CSV</span>
              <input
                id="csv-file-input"
                type="file"
                name="csv_file"
                accept=".csv"
                required
                class="file-picker-input"
              />
            </label>
            <p class="mt-3 text-sm text-muted">
              Campos aceitos: <code>nome,telefone,email</code> ou <code>NOME_CLIENTE,TELEFONE,E_MAIL</code>.
            </p>
          </div>
          <div class="flex flex-wrap gap-2">
            <button type="submit" id="upload-submit" class="secondary-button">Enviar CSV</button>
            <button type="button" id="manual-contact-toggle" class="secondary-button">Adicionar manualmente</button>
          </div>
        </form>

        <form id="manual-contact-form" class="hidden space-y-3 rounded-lg border border-line bg-press p-4">
          <div>
            <p class="text-xs font-medium text-brand">Cadastro manual</p>
            <p class="mt-1 text-sm text-muted">Preencha os dados do cliente para adicionar sem CSV.</p>
          </div>
          <div class="grid gap-3 md:grid-cols-2">
            <label class="block space-y-1.5 md:col-span-2">
              <span class="text-sm font-medium text-muted">Nome <span class="text-danger">*</span></span>
              <input
                type="text" name="name" required maxlength="120"
                class="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20"
              />
            </label>
            <label class="block space-y-1.5">
              <span class="text-sm font-medium text-muted">Telefone <span class="text-danger">*</span></span>
              <input
                type="text" name="phone" required maxlength="30" placeholder="+55 81999999999"
                class="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20"
              />
              <p class="text-xs text-muted">Formato: +55 DDD + numero</p>
            </label>
            <label class="block space-y-1.5">
              <span class="text-sm font-medium text-muted">E-mail <span class="text-muted">(opcional)</span></span>
              <input
                type="email" name="email" maxlength="255" placeholder="cliente@empresa.com"
                class="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20"
              />
            </label>
          </div>
          <div class="flex flex-wrap gap-2">
            <button type="submit" id="manual-contact-submit" class="secondary-button">Salvar cliente</button>
            <button type="button" id="manual-contact-cancel" class="secondary-button">Fechar</button>
          </div>
          <p id="manual-contact-feedback" class="text-sm text-muted">Nome e telefone sao obrigatorios.</p>
        </form>

        <div id="upload-summary" class="rounded-lg border border-line bg-press p-4">
          <p class="text-sm font-medium text-ink">Nenhum CSV enviado ainda.</p>
          <p class="mt-1 text-sm text-muted">Envie sua base para liberar a simulacao e o teste controlado.</p>
        </div>
      </div>
    </div>
  </div>

  <!-- Passo 4: Validar base -->
  <div class="accordion-step" data-step-key="3" data-step-state="blocked">
    <button class="accordion-step__header" type="button" data-accordion-trigger="3">
      <span class="accordion-step__number">4</span>
      <span class="accordion-step__label">Validar base de contatos</span>
      <span class="accordion-step__status"></span>
      <svg class="accordion-step__chevron" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <path d="m5 7.5 5 5 5-5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </button>
    <div class="accordion-step__body">
      <div class="mt-4">
        <article class="contacts-shell min-w-0">
          <div class="contacts-layout">
            <div class="contacts-header">
              <div class="contacts-header__title">
                <p class="text-xs font-medium text-muted">Base de contatos</p>
                <h2 class="mt-1 text-lg font-semibold text-ink">Contatos importados</h2>
              </div>
              <button
                type="button"
                id="clear-imported-contacts"
                class="danger-button contacts-header__clear hidden whitespace-nowrap"
                data-testid="clear-imported-contacts"
              >
                Limpar base importada
              </button>
            </div>

            <form method="get" action="/campaigns/{{ campaign.id }}" class="contacts-toolbar">
              <div class="contacts-toolbar__group">
                <label for="status-filter-trigger" class="contacts-toolbar__label">Filtrar</label>
                <div class="filter-select-shell">
                  <input type="hidden" id="status-filter-input" name="status" value="{{ contacts_status_filter or '' }}" />
                  <button
                    id="status-filter-trigger"
                    type="button"
                    class="filter-select-trigger"
                    aria-haspopup="listbox"
                    aria-expanded="false"
                    aria-controls="status-filter-menu"
                    data-testid="status-filter-trigger"
                  >
                    <span id="status-filter-label">Todos</span>
                    <svg class="h-4 w-4 text-muted transition-transform" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                      <path d="m5 7.5 5 5 5-5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                  </button>
                  <div id="status-filter-menu" class="filter-select-menu hidden" role="listbox" aria-labelledby="status-filter-trigger">
                    <button type="button" class="filter-option" role="option" data-value="">
                      <span class="filter-option__check" aria-hidden="true">✓</span>
                      <span>Todos</span>
                    </button>
                    <button type="button" class="filter-option" role="option" data-value="pending">
                      <span class="filter-option__check" aria-hidden="true">✓</span>
                      <span>Prontos para envio</span>
                    </button>
                    <button type="button" class="filter-option" role="option" data-value="processing">
                      <span class="filter-option__check" aria-hidden="true">✓</span>
                      <span>Em processamento</span>
                    </button>
                    <button type="button" class="filter-option" role="option" data-value="sent">
                      <span class="filter-option__check" aria-hidden="true">✓</span>
                      <span>Enviados</span>
                    </button>
                    <button type="button" class="filter-option" role="option" data-value="failed">
                      <span class="filter-option__check" aria-hidden="true">✓</span>
                      <span>Falhas</span>
                    </button>
                    <button type="button" class="filter-option" role="option" data-value="invalid">
                      <span class="filter-option__check" aria-hidden="true">✓</span>
                      <span>Invalidos</span>
                    </button>
                  </div>
                </div>
              </div>
              <div class="contacts-toolbar__group contacts-toolbar__group--compact">
                <label for="contacts-per-page" class="contacts-toolbar__label">Por pagina</label>
                <select
                  id="contacts-per-page"
                  name="per_page"
                  class="rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-muted outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20"
                >
                  {% for option in [10, 25, 50] %}
                  <option value="{{ option }}" {% if contacts_page_size == option %}selected{% endif %}>{{ option }}</option>
                  {% endfor %}
                </select>
              </div>
            </form>

            <div class="contacts-summary-grid">
              <div class="contacts-summary-card">
                <p class="metric-label">Validos</p>
                <p id="valid-count" class="mt-1 text-xl font-semibold text-ink">{{ stats.valid }}</p>
              </div>
              <div class="contacts-summary-card">
                <p class="metric-label">Invalidos</p>
                <p id="invalid-count" class="mt-1 text-xl font-semibold text-ink">{{ stats.invalid }}</p>
              </div>
              <div class="contacts-summary-card contacts-summary-card--wide">
                <p class="metric-label">Total importado</p>
                <p id="total" class="mt-1 text-xl font-semibold text-ink">{{ stats.total }}</p>
              </div>
              <div class="contacts-summary-card contacts-summary-card--wide">
                <p class="metric-label">Resumo atual</p>
                <p id="contacts-ready-copy" class="mt-1 text-base font-medium text-ink">Aguardando importacao</p>
              </div>
            </div>

            <p id="contacts-meta" class="contacts-meta">
              Total exibido: {{ contacts|length }} de {{ contacts_total }} registros. Pagina {{ contacts_page }} de {{ contacts_total_pages }}.
            </p>

            <div data-testid="contacts-table-wrap" class="contacts-table-wrap overflow-x-auto">
              <table class="contacts-table min-w-full text-sm">
                <thead class="text-left text-xs font-medium text-muted">
                  <tr>
                    <th class="px-3 py-2.5">ID</th>
                    <th class="px-3 py-2.5">Nome</th>
                    <th class="px-3 py-2.5">Telefone CSV</th>
                    <th class="px-3 py-2.5">Telefone valido</th>
                    <th class="px-3 py-2.5">Email</th>
                    <th class="px-3 py-2.5">Status</th>
                    <th class="px-3 py-2.5">Observacao</th>
                    <th class="px-3 py-2.5">Acao</th>
                  </tr>
                </thead>
                <tbody id="contacts-body" class="divide-y divide-line bg-surface">
                  {% for c in contacts %}
                  <tr>
                    <td class="px-3 py-2.5">{{ c.id }}</td>
                    <td class="px-3 py-2.5">{{ c.name }}</td>
                    <td class="px-3 py-2.5">{{ c.phone_raw }}</td>
                    <td class="px-3 py-2.5">{{ c.phone_e164 or '-' }}</td>
                    <td class="px-3 py-2.5">{{ c.email }}</td>
                    <td class="px-3 py-2.5">
                      <span class="contact-status-pill contact-status-pill--{{ c.status }}">{{ CONTACT_PT.get(c.status, c.status) }}</span>
                    </td>
                    <td class="px-3 py-2.5">{{ c.error_message or '-' }}</td>
                    <td class="px-3 py-2.5">
                      {% if campaign.status in ['draft', 'ready', 'paused'] %}
                      <button
                        type="button"
                        class="table-action-button table-action-button--danger"
                        data-contact-action="delete"
                        data-contact-id="{{ c.id }}"
                        data-contact-name="{{ c.name }}"
                      >
                        Excluir
                      </button>
                      {% else %}
                      <span class="text-xs text-muted">Bloqueado</span>
                      {% endif %}
                    </td>
                  </tr>
                  {% else %}
                  <tr>
                    <td colspan="8" class="px-3 py-8 text-center text-sm text-muted">Nenhum contato para este filtro.</td>
                  </tr>
                  {% endfor %}
                </tbody>
              </table>
            </div>

            <div id="contacts-pagination" class="contacts-pagination">
              <button type="button" id="contacts-prev-page" class="secondary-button" {% if contacts_page <= 1 %}disabled{% endif %}>
                Anterior
              </button>
              <span id="contacts-page-indicator" class="rounded-md border border-line bg-press px-3 py-2 text-sm font-medium text-muted">
                Pagina {{ contacts_page }} de {{ contacts_total_pages }}
              </span>
              <button type="button" id="contacts-next-page" class="secondary-button" {% if contacts_page >= contacts_total_pages %}disabled{% endif %}>
                Proxima
              </button>
            </div>
          </div>
        </article>
      </div>
    </div>
  </div>

  <!-- Passo 5: Testar envio -->
  <div class="accordion-step" data-step-key="4" data-step-state="blocked">
    <button class="accordion-step__header" type="button" data-accordion-trigger="4">
      <span class="accordion-step__number">5</span>
      <span class="accordion-step__label">Testar envio</span>
      <span class="accordion-step__status"></span>
      <svg class="accordion-step__chevron" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <path d="m5 7.5 5 5 5-5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </button>
    <div class="accordion-step__body">
      <div class="mt-4 space-y-3">
        <p class="text-sm text-muted">
          Envie uma mensagem de teste antes de disparar para toda a base. O teste usa o mesmo template configurado no passo 2.
          Use o botao <strong class="text-ink">Simular envio</strong> acima para executar o teste.
        </p>
        <div class="rounded-lg border border-line bg-press p-4">
          <p class="text-xs font-medium text-muted">Perfil de velocidade</p>
          <div class="mt-2 flex items-center gap-2">
            <span id="runtime-profile-badge" class="status-badge status-badge--muted">Perfil conservador</span>
            <span id="runtime-profile-copy" class="text-xs text-muted">Fonte: preset</span>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Passo 6: Enviar campanha -->
  <div class="accordion-step" data-step-key="5" data-step-state="blocked">
    <button class="accordion-step__header" type="button" data-accordion-trigger="5">
      <span class="accordion-step__number">6</span>
      <span class="accordion-step__label">Configurar e enviar</span>
      <span class="accordion-step__status"></span>
      <svg class="accordion-step__chevron" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <path d="m5 7.5 5 5 5-5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </button>
    <div class="accordion-step__body">
      <div class="mt-4 space-y-4">

        <!-- Resumo antes do envio -->
        <div class="rounded-lg border border-line bg-press p-4">
          <p class="text-xs font-medium text-muted">Resumo pre-envio</p>
          <div class="mt-2 flex flex-wrap gap-4 text-sm">
            <span><span class="text-muted">Validos:</span> <strong id="pre-send-valid" class="text-ink">{{ stats.valid }}</strong></span>
            <span><span class="text-muted">Invalidos:</span> <strong class="text-ink">{{ stats.invalid }}</strong></span>
            <span><span class="text-muted">Total:</span> <strong class="text-ink">{{ stats.total }}</strong></span>
          </div>
          <div class="mt-2 flex flex-wrap gap-3 text-sm">
            <span><span class="text-muted">Enviados hoje:</span> <span id="daily-limit-summary" class="text-ink">0</span></span>
            <span><span class="text-muted">Resultado:</span> <span id="result-value" class="text-ink">Aguardando</span></span>
          </div>
          <p id="progress-summary" class="mt-1 text-xs text-muted">Nenhuma atividade registrada ainda.</p>
          <p id="result-note" class="mt-0.5 text-xs text-muted">Sem envio em andamento.</p>
        </div>

        <!-- Configuracoes avancadas (colapsado por padrao) -->
        <details class="rounded-lg border border-line bg-press">
          <summary class="flex cursor-pointer items-center gap-2 px-4 py-3 text-sm font-medium text-muted select-none hover:text-ink">
            <svg class="h-4 w-4" viewBox="0 0 20 20" fill="none" aria-hidden="true">
              <circle cx="10" cy="10" r="7.5" stroke="currentColor" stroke-width="1.5"/>
              <path d="M10 6.5v3.5l2.5 2.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
            Configuracoes avancadas
          </summary>
          <form id="settings-form" class="settings-shell border-t border-line">
            <div class="settings-header">
              <div>
                <p class="text-xs font-medium text-brand">Configuracoes operacionais</p>
                <p class="mt-1 text-sm text-muted">Ritmo, janela e seguranca operacional da campanha.</p>
              </div>
              <span id="settings-window-pill" class="settings-window-pill">Janela: {{ stats.send_window_start or '08:00' }}-{{ stats.send_window_end or '20:00' }}</span>
            </div>
            <input type="hidden" name="speed_profile" value="{{ stats.speed_profile or 'conservative' }}" />
            <div class="settings-profile-shell">
              <div class="speed-profile-switch" role="group" aria-label="Modo de velocidade">
                <button type="button" class="speed-profile-option" data-speed-profile="conservative">Conservador</button>
                <button type="button" class="speed-profile-option" data-speed-profile="aggressive">Agressivo</button>
              </div>
              <div class="speed-profile-meta">
                <span id="speed-profile-badge" class="status-badge status-badge--muted">Conservador</span>
                <p id="speed-profile-description" class="text-sm text-muted">Conservador: prioriza estabilidade e previsibilidade.</p>
              </div>
            </div>
            <div class="settings-window-grid">
              <label class="block space-y-1.5">
                <span class="text-sm font-medium text-muted">Inicio da janela</span>
                <input type="time" step="3600" name="send_window_start" value="{{ stats.send_window_start or '08:00' }}"
                  class="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20"/>
              </label>
              <label class="block space-y-1.5">
                <span class="text-sm font-medium text-muted">Fim da janela</span>
                <input type="time" step="3600" name="send_window_end" value="{{ stats.send_window_end or '20:00' }}"
                  class="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20"/>
              </label>
            </div>
            <div class="settings-input-grid">
              <label class="block space-y-1.5">
                <span class="text-sm font-medium text-muted">Atraso minimo (s)</span>
                <input type="number" min="1" max="3600" name="send_delay_min_seconds" value="{{ stats.send_delay_min_seconds or 15 }}"
                  class="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20"/>
              </label>
              <label class="block space-y-1.5">
                <span class="text-sm font-medium text-muted">Atraso maximo (s)</span>
                <input type="number" min="1" max="3600" name="send_delay_max_seconds" value="{{ stats.send_delay_max_seconds or 45 }}"
                  class="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20"/>
              </label>
              <label class="block space-y-1.5">
                <span class="text-sm font-medium text-muted">Pausa min. lote (s)</span>
                <input type="number" min="0" max="3600" name="batch_pause_min_seconds" value="{{ stats.batch_pause_min_seconds or 25 }}"
                  class="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20"/>
              </label>
              <label class="block space-y-1.5">
                <span class="text-sm font-medium text-muted">Pausa max. lote (s)</span>
                <input type="number" min="0" max="3600" name="batch_pause_max_seconds" value="{{ stats.batch_pause_max_seconds or 40 }}"
                  class="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20"/>
              </label>
              <label class="block space-y-1.5">
                <span class="text-sm font-medium text-muted">Max. envios/dia</span>
                <input type="number" min="0" name="daily_limit" value="{{ stats.daily_limit or 0 }}"
                  class="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20"/>
                <p class="text-xs text-muted">0 = sem limite diario.</p>
              </label>
            </div>
            <div class="settings-actions">
              <button type="submit" id="save-settings-button" class="secondary-button">Salvar configuracoes</button>
            </div>
          </form>
        </details>

      </div>
    </div>
  </div>

</div>
```

### Step 5: Remover elementos órfãos

Após a reestruturação, verificar e remover os seguintes elementos que foram relocados:
- `#primary-rule` (o texto "Uma unica acao dominante por estado" — remover ou manter hidden)
- Antigo `data-testid="campaign-stepper"` do template original

---

## Task 3: JS — Atualizar `renderStepper` e adicionar accordion em `static/app.js`

**Files:**
- Modify: `static/app.js`

### Step 1: Localizar e atualizar `const stepItems` (linha ~115)

Substituir:
```js
const stepItems = Array.from(document.querySelectorAll('.stepper-item'));
```
Por:
```js
const stepItems = Array.from(document.querySelectorAll('[data-step-key]'));
```

### Step 2: Atualizar `renderStepper` para também controlar o accordion (linha ~871)

Substituir o conteúdo da função `renderStepper`:
```js
function renderStepper(uiState, currentStats, session) {
  const states = getStepperState(uiState, currentStats, session);
  stepItems.forEach((item, index) => {
    const state = states[index] || 'blocked';
    item.dataset.stepState = state;
    const dot = item.querySelector('.stepper-item__dot');
    if (dot) dot.textContent = state === 'done' ? '✓' : String(index + 1);
  });
}
```
Por:
```js
function renderStepper(uiState, currentStats, session) {
  const states = getStepperState(uiState, currentStats, session);
  const statusLabels = {
    done: 'Concluido',
    active: 'Em andamento',
    blocked: '',
  };
  stepItems.forEach((item, index) => {
    const state = states[index] || 'blocked';
    const wasActive = item.dataset.stepState === 'active';
    item.dataset.stepState = state;

    // Atualizar número/ícone no header
    const numEl = item.querySelector('.accordion-step__number');
    if (numEl) numEl.textContent = state === 'done' ? '✓' : String(index + 1);

    // Atualizar label de status
    const statusEl = item.querySelector('.accordion-step__status');
    if (statusEl) statusEl.textContent = statusLabels[state] || '';

    // Desabilitar header se bloqueado
    const headerBtn = item.querySelector('[data-accordion-trigger]');
    if (headerBtn) headerBtn.disabled = state === 'blocked';

    // Remover is-open de passos que saíram do estado done (opcional)
    if (state === 'active') item.classList.remove('is-open');
  });
}
```

### Step 3: Adicionar handler de click para accordion (adicionar logo após o bloco de `stepItems`)

Encontrar no app.js a linha após a declaração de `stepItems` (linha ~115) e adicionar:

```js
// Accordion click handler
document.querySelectorAll('[data-accordion-trigger]').forEach((btn) => {
  btn.addEventListener('click', () => {
    const step = btn.closest('[data-step-key]');
    if (!step) return;
    const state = step.dataset.stepState;
    if (state === 'blocked') return;
    if (state === 'done') {
      step.classList.toggle('is-open');
    }
    // Estado 'active' não fecha (sempre aberto via CSS)
  });
});
```

### Step 4: Verificar que elementos não usados são ignorados graciosamente

O JS referencia `#progress-fill` e `#progress-caption` — agora estão na stats-strip-top. Os IDs são os mesmos, então funciona sem mudança.

O JS referencia `#total`, `#valid-count`, `#invalid-count` — agora estão no passo 4. OK.

O JS referencia `#runtime-profile-badge`, `#runtime-profile-copy` — agora no passo 5. OK.

O JS referencia `#daily-limit-summary`, `#result-value`, `#result-note`, `#progress-summary` — agora no passo 6. OK.

O JS referencia `#primary-rule` — removido do HTML. Adicionar guard no app.js:

Buscar por `primaryRule` no app.js e envolver qualquer atribuição com `if (primaryRule)`:

```js
// Antes: primaryRule.textContent = '...'
// Depois:
if (primaryRule) primaryRule.textContent = '...';
```

---

## Task 4: Commit e verificação

### Step 1: Verificar no browser

```bash
# Iniciar o servidor (ajustar conforme o projeto)
python server.py  # ou o comando correto
```

Abrir `http://localhost:XXXX/campaigns/ALGUM_ID` e verificar:
- Stats strip visível no topo com progress bar
- Card "Ação atual" com botão correto
- Accordion com 6 passos
- Passo 1 ativo (se WhatsApp desconectado)
- Passos bloqueados em cinza, não clicáveis
- Passos concluídos com ✓ verde, clicáveis para revisar

### Step 2: Commit de ponto de controle

```bash
git add templates/campaign.html static/styles.css static/app.js
git commit -m "feat(campaign): accordion step flow — guided 6-step onboarding

Replaces flat wall-of-forms layout with guided accordion:
- Compact stats strip always visible (progress, sent, failed, pending, ETA)
- Persistent 'Acao atual' card with primary action button
- 6 accordion steps driven by existing JS state machine
- Advanced settings collapsed inside step 6
- No backend changes"
```

---

## Notas de rollback

Se algo der errado:
```bash
git checkout pre-accordion-redesign -- templates/campaign.html static/app.js static/styles.css
```
