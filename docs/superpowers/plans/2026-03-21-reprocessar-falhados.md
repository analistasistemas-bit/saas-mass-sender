# Reprocessar Falhados Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expor na UI concluida uma acao para reenfileirar apenas falhas e mostrar indicadores do reprocessamento na secao de resultados

**Architecture:** O endpoint de restart existente continua sendo a unica acao backend. O payload de resultados passa a informar se houve um restart parcial por falha e qual o estado atual dessa fila. A UI consome esse bloco para renderizar uma area separada, preservando o resumo principal da campanha concluida.

**Tech Stack:** FastAPI, SQLAlchemy, Jinja2, JavaScript vanilla, Playwright, pytest

---

### Task 1: Cobrir payload de reprocessamento

**Files:**
- Modify: `/Users/mac/Desktop/IA/mass-sender/tests/test_campaign_actions_ui_payloads.py`
- Modify: `/Users/mac/Desktop/IA/mass-sender/services/campaign_service.py`

- [ ] **Step 1: Write the failing test**
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Write minimal implementation**
- [ ] **Step 4: Run test to verify it passes**

### Task 2: Expor acao e painel na interface

**Files:**
- Modify: `/Users/mac/Desktop/IA/mass-sender/tests/e2e/operational.spec.js`
- Modify: `/Users/mac/Desktop/IA/mass-sender/templates/campaign.html`
- Modify: `/Users/mac/Desktop/IA/mass-sender/static/app.js`

- [ ] **Step 1: Write the failing UI expectation**
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Write minimal implementation**
- [ ] **Step 4: Run test to verify it passes**

### Task 3: Verificacao final

**Files:**
- Verify: `/Users/mac/Desktop/IA/mass-sender/tests/test_campaign_actions_ui_payloads.py`
- Verify: `/Users/mac/Desktop/IA/mass-sender/tests/e2e/operational.spec.js`

- [ ] **Step 1: Run targeted pytest**
- [ ] **Step 2: Run targeted Playwright**
- [ ] **Step 3: Confirm no regression in changed flow**
