# Brandbook — Mass Sender

## Arquitetura de marca

Mass Sender é a marca de produto. Use seu logo sozinho em produto, campanhas e materiais comerciais.

Daludi é a marca corporativa. No produto, ela aparece centralizada no masthead como `DALUDI | INNOVIT CONSULT`. Não use `by Daludi`, não una os dois símbolos em uma só assinatura e não substitua o logo da Daludi pelo símbolo Cofre.

## Logos e espaço livre

O símbolo Mass Sender é o **Cofre**: aro octogonal turquesa, miolo escuro e núcleo lime. Use SVG sempre que possível; use PNG somente onde SVG não for aceito.

- Mantenha ao redor do Cofre uma área livre igual à largura do núcleo lime.
- Não reduza o Cofre abaixo de 32 px.
- Não estique, gire, redesenhe ou aplique sombra, glow ou gradiente nos logos.
- `static/brand/daludi-logo.png` é o PNG oficial fornecido. Não altere símbolo, cor ou proporção. Para layout digital, use o recorte derivado `static/brand/png/daludi-logo-digital.png`.

## Paleta e tipografia

| Papel | Token | Valor |
|---|---|---|
| Fundo | `--bg-base` | `#0B1112` |
| Superfície | `--bg-surface` | `#121B1D` |
| Superfície elevada | `--bg-elevated` | `#182527` |
| Sinal / ação principal | `--brand-signal` | `#2BCAC2` |
| Sucesso | `--semantic-success` | `#C5FF64` |
| Texto principal | `--text-base` | `#EEF8F7` |
| Texto secundário | `--text-subdued` | `#91A5A6` |

Use Manrope para títulos e Inter para texto de interface. O produto é dark-first: não crie versões claras sem uma aprovação de marca específica.

## Produto e campanhas

No app, preserve o masthead Daludi centralizado e use o lockup horizontal do Mass Sender na navegação ou área de produto. Turquesa sinaliza ações principais; lime é reservado para sucesso, conexão ativa e o núcleo do Cofre. Status de erro usam rosa e alertas usam âmbar — nunca lime.

Para campanhas, mantenha contraste alto, um foco principal por peça e o Mass Sender como marca dominante. A assinatura Daludi é institucional e discreta.

## Arquivos aprovados

| Arquivo | Uso |
|---|---|
| `static/brand/mass-sender-cofre-symbol.svg` | ícone, avatar, favicon |
| `static/brand/mass-sender-cofre-horizontal.svg` | app, cabeçalhos, mídia horizontal |
| `static/brand/mass-sender-cofre-stacked.svg` | composição vertical |
| `static/brand/png/mass-sender-cofre-horizontal-2048.png` | exportação de alta densidade |
| `static/brand/png/daludi-logo-digital.png` | assinatura corporativa digital |
| `static/brand/png/favicon-*.png` | navegador e ícones de app |

Veja `static/brand/README.md` para o inventário PNG completo e limites de tamanho.

## Tamanhos de mídia social

| Peça | Tamanho |
|---|---:|
| Post quadrado | 1080 × 1080 px |
| Story / Reel | 1080 × 1920 px |
| Link / anúncio horizontal | 1200 × 628 px |

Exporte em PNG para redes sociais. Em arquivos de criação, mantenha o SVG master vinculado para evitar perda de qualidade.
