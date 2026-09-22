# Design: Accordion Step Flow para Tela de Campanha

**Data:** 2026-04-19  
**Status:** Aprovado  
**Rollback:** `git checkout pre-accordion-redesign -- templates/campaign.html static/app.js static/styles.css`

---

## Problema

A tela de campanha exibe todos os formulários ao mesmo tempo (mensagem, configurações, CSV, contatos), tornando o fluxo confuso para usuários operacionais que não sabem por onde começar.

## Solução

Transformar a tela num **accordion de 6 passos** onde apenas o passo ativo fica expandido. Passos concluídos ficam colapsados (mas clicáveis). Passos bloqueados ficam acinzentados e não clicáveis.

---

## Arquitetura

### Layout geral

```
Header: Nome da campanha + badge de status
Barra de progresso compacta (sempre visível): Enviados | Falhas | Pendentes | ETA

Accordion:
  1. Conectar WhatsApp  [✓ / ▶ / 🔒]
  2. Preparar mensagem  [✓ / ▶ / 🔒]
  3. Importar contatos  [✓ / ▶ / 🔒]
  4. Validar base       [✓ / ▶ / 🔒]
  5. Testar envio       [✓ / ▶ / 🔒]
  6. Enviar campanha    [✓ / ▶ / 🔒]

Seção de Atividade/Logs (sempre visível, abaixo do accordion)
Seção de Resultados (visível apenas quando status=completed)
```

### Estados dos passos

| Estado    | Visual                              | Interação       |
|-----------|-------------------------------------|-----------------|
| Concluído | Header verde, ícone ✓               | Clicável (revisão) |
| Ativo     | Header com borda brand, expandido   | Sempre aberto   |
| Bloqueado | Header acinzentado, ícone 🔒        | Não clicável    |

### Mapeamento status → passo ativo

| Status da campanha | Passo ativo |
|--------------------|-------------|
| `draft` sem bridge | 1           |
| `draft` com bridge, sem contatos | 2 ou 3 |
| `draft` com contatos, não validado | 4     |
| `ready`            | 5 (testar)  |
| `ready` + testado  | 6 (enviar)  |
| `running`/`paused` | 6           |
| `completed`        | Todos concluídos, resultados visíveis |

---

## Conteúdo de cada passo

### Passo 1 — Conectar WhatsApp
- Cards de saúde dos serviços (Motor + Bridge)
- Botão de ação primária (QR / Reconectar)
- Narrativa de status

### Passo 2 — Preparar mensagem
- Textarea da mensagem
- Dica de variável `{{nome}}`
- Botão "Salvar mensagem"

### Passo 3 — Importar contatos
- Zona de upload CSV
- Botão "Adicionar manualmente"
- Formulário manual (colapsado por padrão)

### Passo 4 — Validar base
- Cards: Válidos / Inválidos / Total
- Tabela de contatos com filtro e paginação
- Botão "Validar contatos"

### Passo 5 — Testar envio
- Botão de teste
- Resultado do teste

### Passo 6 — Enviar campanha
- Resumo: X contatos válidos, mensagem configurada
- Sub-accordion "⚙ Configurações avançadas" (colapsado por padrão):
  - Perfil de velocidade (conservador / agressivo)
  - Janela de envio (início / fim)
  - Delays (mín/máx por mensagem, mín/máx por lote)
  - Limite diário
- Botão "Iniciar envio" (destaque)

---

## Componentes novos (CSS)

- `.accordion-step` — container de cada passo
- `.accordion-step__header` — clicável, mostra número + nome + ícone de estado
- `.accordion-step__body` — conteúdo colapsável
- `.accordion-step--active` — borda brand, body visível
- `.accordion-step--done` — header verde, body colapsado
- `.accordion-step--locked` — header acinzentado, não clicável
- `.stats-strip-compact` — barra de métricas sempre visível no topo

## Mudanças no JS (app.js)

- Adicionar função `setActiveStep(index)` que aplica classes nos accordions
- Mapear o estado atual da campanha (bridge, contacts, status) para o índice de passo
- Manter toda a lógica de polling e actions existente intacta
- Accordion click: passos concluídos toggleam ao clicar; ativo não fecha; bloqueados ignoram click

## Arquivos modificados

- `templates/campaign.html` — reorganização do HTML em accordion
- `static/styles.css` — novos componentes de accordion
- `static/app.js` — lógica de step ativo

## O que NÃO muda

- Lógica de backend (sem mudanças em Python)
- Polling e estado da campanha
- Toda a funcionalidade existente dos formulários
- Seção de Resultados e Activity/Logs
