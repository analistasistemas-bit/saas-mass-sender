# Brandbook e Design System — Mass Sender

## Objetivo

Transformar o Mass Sender em um SaaS de controle premium, escuro, técnico e confiável. A Daludi aparece como empresa institucional; Mass Sender é uma marca de produto independente.

## Arquitetura de marca

- **Daludi:** marca proprietária, centralizada no masthead do aplicativo.
- **Assinatura Daludi:** símbolo oficial + `DALUDI` + divisor + `INNOVIT CONSULT`.
- **Mass Sender:** marca do produto, na navegação e nas peças de campanha.
- **Proibido:** lockup único com as duas logos, texto “by Daludi”, substituir uma marca pelo símbolo da outra.

## Identidade Mass Sender

- **Símbolo aprovado:** Cofre — moldura octogonal angular com núcleo central.
- **Ideia:** infraestrutura de comunicação protegida, precisa e sob controle.
- **Tom:** calmo, premium, operacional; nunca neon, informal ou inspirado em Spotify.
- **Wordmark:** `MASS SENDER`, peso alto, compacto, com `SENDER` em turquesa.
- **Família visual:** parentesco discreto com a Daludi apenas por geometria angular e turquesa; o símbolo deve ser exclusivo.

## Tema e tokens

| Token | Valor | Uso |
|---|---:|---|
| `--bg-base` | `#0B1112` | Fundo principal |
| `--bg-surface` | `#121B1D` | Cards e painéis |
| `--bg-elevated` | `#182527` | Estados elevados e hover |
| `--text-primary` | `#EEF8F7` | Texto principal |
| `--text-muted` | `#91A5A6` | Texto secundário |
| `--brand-signal` | `#2BCAC2` | Ação primária e foco |
| `--semantic-success` | `#C5FF64` | Conexão e sucesso |
| `--semantic-warning` | `#F4BD63` | Atenção |
| `--semantic-danger` | `#FF7F8A` | Falha e ação destrutiva |

- Tema oficial: dark-first. Modo claro não integra esta etapa.
- Tipografia: Manrope para títulos; Inter para interface, formulários e dados.
- Raios: 8px em botões; 10px em cards. Pílulas não são padrão do sistema.
- Turquesa é reservado para prioridade, ação e estado ativo.

## Aplicação no aplicativo

1. Masthead Daludi centralizado, com altura de referência de 92px no desktop.
2. Navegação lateral começa com o lockup Mass Sender Cofre.
3. A área operacional permanece densa e silenciosa; cards usam superfície escura e borda sutil.
4. Ação principal é turquesa; ações secundárias são contornadas; ações de risco usam rosa/vermelho discreto.
5. A marca Daludi usa sempre o arquivo oficial; nenhum redesenho aproximado entra em produção.

## Pacote de ativos a produzir

### Mass Sender

- `mass-sender-cofre-symbol.svg` — símbolo isolado.
- `mass-sender-cofre-horizontal.svg` — símbolo + wordmark horizontal.
- `mass-sender-cofre-stacked.svg` — símbolo + wordmark empilhado.
- PNG transparente dos três lockups em 512px, 1024px e 2048px.
- `favicon.ico` e PNG 16px, 32px, 48px, 180px e 512px.
- Versões em turquesa, gelo e monocromática para fundos escuros, claros e impressão.

### Daludi

- SVG oficial fornecido pela Daludi, sem reconstrução.
- PNG transparente de apoio em 512px e 2048px.
- Lockup institucional `DALUDI | INNOVIT CONSULT` aprovado a partir do arquivo oficial e da tipografia correta.

### Marketing e social

- Avatar: símbolo Mass Sender 1:1.
- Capa: lockup horizontal Mass Sender com área de respiro.
- Templates para post 1080×1080, story 1080×1920 e banner 1200×628.
- Todos os templates devem usar os mesmos tokens, tipografia e margens de proteção.

## Dependência externa antes da produção final

O proprietário deve fornecer o arquivo oficial da Daludi, preferencialmente SVG. A imagem enviada nesta conversa é referência visual e não deve ser usada como ativo final.

## Critérios de aceitação

- Mass Sender e Daludi são reconhecíveis e independentes em 32px.
- A interface aplica os tokens sem resquícios da estética Spotify anterior.
- Os ativos SVG e PNG funcionam em aplicativo, marketing e mídia social.
- A composição do cabeçalho reproduz o lockup Daludi oficial centralizado com `INNOVIT CONSULT`.
