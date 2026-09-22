# Mass Sender Brand System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the approved Mass Sender Cofre identity, the centered Daludi masthead, reusable dark-first tokens, and the digital asset kit for app and social use.

**Architecture:** Brand assets live under `static/brand/`; a Jinja partial renders the Daludi masthead consistently; `static/styles.css` owns all product tokens and brand primitives. Templates consume those primitives without changing backend routes or operational JavaScript. Marketing exports derive only from the approved SVG masters and the supplied Daludi transparent PNG.

**Tech Stack:** FastAPI/Jinja templates, Tailwind CDN, CSS custom properties, SVG, PNG, Playwright, pytest, macOS `sips` for PNG inspection/export.

**Spec:** `docs/superpowers/specs/2026-09-22-mass-sender-brand-system-design.md`

## Global Constraints

- Preserve every campaign route, form action, `id`, `data-testid`, and operational JavaScript contract.
- Use the supplied Daludi transparent PNG unchanged in symbol, color, and proportion; do not recreate the Daludi mark.
- Use Mass Sender Cofre as an independent mark; never combine its logo with Daludi or write “by Daludi”.
- Dark-first only: base `#0B1112`, surface `#121B1D`, elevated `#182527`, signal `#2BCAC2`, success `#C5FF64`.
- Use Manrope for headings and Inter for UI/body; standard radii are 8px buttons and 10px cards.
- Add no runtime frontend framework or backend dependency.

## Review Focus

- A missing brand PNG must show readable fallback text instead of breaking login or navigation.
- The desktop masthead must center the complete Daludi lockup, not just its icon.
- A 320px viewport must retain both brand names without horizontal overflow.
- Existing campaign controls and test IDs must remain addressable after the shared header is inserted.
- Source PNG whitespace must not cause a tiny Daludi logo in the masthead or social exports.

---

## File Structure

| Path | Responsibility |
|---|---|
| `static/brand/` | Immutable source and exported Mass Sender/Daludi assets plus usage manifest. |
| `static/brand/mass-sender-cofre-*.svg` | Cofre symbol and approved horizontal/stacked Mass Sender lockups. |
| `static/brand/daludi-logo.png` | User-supplied official transparent Daludi PNG, preserved as source. |
| `static/brand/README.md` | Asset inventory, allowed variants, clear-space and export rules. |
| `templates/_brand_masthead.html` | Shared centered Daludi institutional masthead. |
| `static/styles.css` | Dark-first tokens, typography, masthead and Mass Sender mark styles. |
| `templates/login.html` | Branded login surface. |
| `templates/index.html`, `templates/campaign.html`, `templates/agent_settings.html` | Masthead and product identity integration. |
| `tests/e2e/brand-system.spec.js` | Browser-level contract for assets, brand hierarchy and responsive layout. |
| `docs/BRANDBOOK.md` | Operator-facing brand rules for app, marketing and social use. |

### Task 1: Establish the brand asset source of truth

**Files:**
- Create: `static/brand/daludi-logo.png`
- Create: `static/brand/mass-sender-cofre-symbol.svg`
- Create: `static/brand/mass-sender-cofre-horizontal.svg`
- Create: `static/brand/mass-sender-cofre-stacked.svg`
- Create: `static/brand/README.md`
- Test: `tests/test_brand_assets.py`

**Interfaces:**
- Consumes: the supplied Daludi PNG attachment and colors specified in the approved spec.
- Produces: public URLs `/static/brand/daludi-logo.png`, `/static/brand/mass-sender-cofre-horizontal.svg`, and `/static/brand/mass-sender-cofre-symbol.svg` for templates and marketing exports.

- [ ] **Step 1: Write the failing asset contract test**

```python
from pathlib import Path


BRAND = Path("static/brand")


def test_brand_source_files_exist_and_svg_lockups_are_named():
    assert (BRAND / "daludi-logo.png").is_file()
    for filename in (
        "mass-sender-cofre-symbol.svg",
        "mass-sender-cofre-horizontal.svg",
        "mass-sender-cofre-stacked.svg",
    ):
        contents = (BRAND / filename).read_text(encoding="utf-8")
        assert "<svg" in contents
        assert "#2BCAC2" in contents
        assert "by Daludi" not in contents
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_brand_assets.py -q`

Expected: FAIL because `static/brand/` and its source assets do not yet exist.

- [ ] **Step 3: Add the supplied Daludi source and Mass Sender masters**

Copy the attachment exactly to `static/brand/daludi-logo.png`. Create the Cofre symbol as an SVG octagonal outline with an inset lime octagon; create horizontal and stacked lockups with the exact text `MASS SENDER`. Keep an explicit `viewBox`, `role="img"`, `<title>`, and only `#2BCAC2`, `#C5FF64`, `#EEF8F7`, and `#0B1112` colors.

```svg
<svg viewBox="0 0 64 64" role="img" aria-labelledby="title">
  <title id="title">Mass Sender Cofre</title>
  <path fill="#2BCAC2" d="M16 0h32l16 16v32L48 64H16L0 48V16z"/>
  <path fill="#0B1112" d="M20 8h24l12 12v24L44 56H20L8 44V20z"/>
  <path fill="#C5FF64" d="M27 20h10l7 7v10l-7 7H27l-7-7V27z"/>
</svg>
```

Document clear space equal to one symbol-core width, minimum symbol size of 32px, and no-glow/no-distortion rules in `static/brand/README.md`.

- [ ] **Step 4: Run asset tests and inspect the source PNG**

Run: `./.venv/bin/pytest tests/test_brand_assets.py -q && sips -g pixelWidth -g pixelHeight -g hasAlpha static/brand/daludi-logo.png`

Expected: pytest passes; `hasAlpha: yes`; source remains `1536×1024`.

- [ ] **Step 5: Commit the asset foundation**

```bash
git add static/brand tests/test_brand_assets.py
git commit -m "feat: add Mass Sender and Daludi brand assets"
```

### Task 2: Replace the visual token layer and add reusable brand primitives

**Files:**
- Modify: `static/styles.css:1-35`
- Modify: `static/styles.css:54-175`
- Test: `tests/test_brand_assets.py`

**Interfaces:**
- Consumes: asset URLs produced by Task 1.
- Produces: CSS variables `--brand-signal`, `--semantic-success`, `.brand-masthead`, `.brand-product-lockup`, and `.brand-logo-fallback` used by Task 3.

- [ ] **Step 1: Extend the failing contract test with token assertions**

```python
def test_brand_tokens_and_primitives_are_declared():
    css = Path("static/styles.css").read_text(encoding="utf-8")
    for token in ("--brand-signal: #2BCAC2", "--semantic-success: #C5FF64", "--font-display"):
        assert token in css
    for selector in (".brand-masthead", ".brand-product-lockup", ".brand-logo-fallback"):
        assert selector in css
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_brand_assets.py::test_brand_tokens_and_primitives_are_declared -q`

Expected: FAIL because the old Spotify-derived token names and primitives are still present.

- [ ] **Step 3: Implement the approved token layer**

Replace the root values while keeping aliases such as `--brand-accent` for existing Tailwind utility compatibility.

```css
:root {
  --bg-base: #0B1112;
  --bg-surface: #121B1D;
  --bg-elevated: #182527;
  --bg-press: #10191B;
  --brand-signal: #2BCAC2;
  --brand-accent: var(--brand-signal);
  --brand-accent-hover: #62DED7;
  --semantic-success: #C5FF64;
  --semantic-warning: #F4BD63;
  --semantic-negative: #FF7F8A;
  --text-base: #EEF8F7;
  --text-subdued: #91A5A6;
  --font-display: 'Manrope', 'Inter', system-ui, sans-serif;
}
```

Define a 92px centered desktop masthead, a 76px mobile masthead, a 10px product-card radius, and a visible `.brand-logo-fallback` text label shown when an image emits `error`.

- [ ] **Step 4: Run the token contract test**

Run: `./.venv/bin/pytest tests/test_brand_assets.py -q`

Expected: PASS.

- [ ] **Step 5: Commit token primitives**

```bash
git add static/styles.css tests/test_brand_assets.py
git commit -m "feat: add Mass Sender dark-first design tokens"
```

### Task 3: Integrate the Daludi masthead and Mass Sender identity without changing workflows

**Files:**
- Create: `templates/_brand_masthead.html`
- Modify: `templates/login.html`
- Modify: `templates/index.html`
- Modify: `templates/campaign.html`
- Modify: `templates/agent_settings.html`
- Test: `tests/e2e/brand-system.spec.js`

**Interfaces:**
- Consumes: `/static/brand/daludi-logo.png`, `/static/brand/mass-sender-cofre-horizontal.svg`, and the CSS classes from Task 2.
- Produces: `header[data-testid="daludi-masthead"]` and `[data-testid="mass-sender-product-mark"]` on every rendered product surface.

- [ ] **Step 1: Write the failing Playwright test**

```javascript
test('aplica a hierarquia Daludi e Mass Sender no login e dashboard', async ({ page }) => {
  await page.goto('/login');
  await expect(page.getByTestId('daludi-masthead')).toBeVisible();
  await expect(page.getByAltText('Daludi')).toHaveAttribute('src', '/static/brand/daludi-logo.png');
  await expect(page.getByTestId('mass-sender-product-mark')).toContainText('Mass Sender');

  await page.getByPlaceholder('Senha').fill('admin123');
  await page.getByRole('button', { name: 'Entrar' }).click();
  await expect(page.getByTestId('daludi-masthead')).toBeVisible();
  await expect(page.getByTestId('mass-sender-product-mark')).toBeVisible();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx playwright test tests/e2e/brand-system.spec.js`

Expected: FAIL because neither brand test ID exists.

- [ ] **Step 3: Add the shared masthead and product mark**

Create `_brand_masthead.html` with an image, an accessible fallback, a centered `.brand-masthead__lockup`, and the literal `INNOVIT CONSULT` text. Include it immediately inside `<body>` in all four templates. Put the Mass Sender horizontal SVG in the login card and the product-page header/navigation area; do not remove campaign buttons, links, IDs, forms, data attributes, or script tags.

```html
<header class="brand-masthead" data-testid="daludi-masthead">
  <div class="brand-masthead__lockup">
    <img src="/static/brand/daludi-logo.png" alt="Daludi" />
    <span class="brand-masthead__divider" aria-hidden="true"></span>
    <span>INNOVIT CONSULT</span>
  </div>
</header>
```

- [ ] **Step 4: Run focused browser coverage at desktop and mobile widths**

Extend `brand-system.spec.js` to set `1440×900` and `320×800`; assert `document.documentElement.scrollWidth === window.innerWidth`, the masthead remains visible, and `data-testid="primary-action"` still works on a campaign page.

Run: `npx playwright test tests/e2e/brand-system.spec.js`

Expected: PASS.

- [ ] **Step 5: Commit template integration**

```bash
git add templates static/styles.css tests/e2e/brand-system.spec.js
git commit -m "feat: apply Daludi and Mass Sender brand hierarchy"
```

### Task 4: Produce app-ready and social-ready PNG exports

**Files:**
- Create: `static/brand/png/mass-sender-cofre-symbol-512.png`
- Create: `static/brand/png/mass-sender-cofre-horizontal-1024.png`
- Create: `static/brand/png/mass-sender-cofre-horizontal-2048.png`
- Create: `static/brand/png/mass-sender-cofre-stacked-1024.png`
- Create: `static/brand/png/daludi-logo-digital.png`
- Create: `static/brand/png/favicon-16.png`
- Create: `static/brand/png/favicon-32.png`
- Create: `static/brand/png/favicon-48.png`
- Create: `static/brand/png/favicon-180.png`
- Create: `static/brand/png/favicon-512.png`
- Modify: `static/brand/README.md`
- Test: `tests/test_brand_assets.py`

**Interfaces:**
- Consumes: SVG master files and `static/brand/daludi-logo.png` from Task 1.
- Produces: named PNG outputs for app metadata, marketing composition and social templates.

- [ ] **Step 1: Add failing export assertions**

```python
def test_png_export_inventory_is_complete():
    expected = {
        "mass-sender-cofre-symbol-512.png", "mass-sender-cofre-horizontal-1024.png",
        "mass-sender-cofre-horizontal-2048.png", "mass-sender-cofre-stacked-1024.png",
        "daludi-logo-digital.png", "favicon-16.png", "favicon-32.png",
        "favicon-48.png", "favicon-180.png", "favicon-512.png",
    }
    actual = {path.name for path in Path("static/brand/png").glob("*.png")}
    assert expected <= actual
```

- [ ] **Step 2: Run the export test to verify it fails**

Run: `./.venv/bin/pytest tests/test_brand_assets.py::test_png_export_inventory_is_complete -q`

Expected: FAIL because export files do not exist.

- [ ] **Step 3: Export non-destructively and document intended use**

Use `sips` to render each Mass Sender SVG to the declared PNG size and resize the Cofre symbol for favicon variants. Crop only transparent padding from a *copy* of Daludi PNG, retain `daludi-logo.png` untouched, and export `daludi-logo-digital.png` for layout use. Add the intended medium and maximum width of every output to `static/brand/README.md`.

```bash
sips -s format png static/brand/mass-sender-cofre-horizontal.svg --out static/brand/png/mass-sender-cofre-horizontal-1024.png
sips -Z 512 static/brand/png/mass-sender-cofre-symbol-512.png --out static/brand/png/favicon-512.png
```

- [ ] **Step 4: Verify file inventory and dimensions**

Run: `./.venv/bin/pytest tests/test_brand_assets.py -q && sips -g pixelWidth -g pixelHeight static/brand/png/favicon-16.png static/brand/png/favicon-512.png`

Expected: pytest passes; favicon outputs report 16px and 512px square dimensions.

- [ ] **Step 5: Commit exports**

```bash
git add static/brand tests/test_brand_assets.py
git commit -m "feat: export Mass Sender digital brand assets"
```

### Task 5: Publish the operational brandbook and protect regressions

**Files:**
- Create: `docs/BRANDBOOK.md`
- Modify: `README.md`
- Test: `tests/e2e/brand-system.spec.js`

**Interfaces:**
- Consumes: approved source files, exports and usage rules from Tasks 1–4.
- Produces: a concise human-facing operating guide and final regression evidence.

- [ ] **Step 1: Add a failing documentation-link assertion**

```python
def test_readme_links_to_brandbook():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "docs/BRANDBOOK.md" in readme
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_brand_assets.py::test_readme_links_to_brandbook -q`

Expected: FAIL because no user-facing brandbook exists.

- [ ] **Step 3: Write the brandbook and link it from the README**

Document hierarchy, correct/incorrect lockups, clear space, color tokens, typography, app use, file inventory, social sizes (`1080×1080`, `1080×1920`, `1200×628`), and the rule that Daludi PNG must not be altered. Add one README link under the existing documentation list.

- [ ] **Step 4: Run complete regression validation**

Run: `./.venv/bin/pytest -q && npx playwright test`

Expected: all backend tests and both existing operational Playwright specs plus `brand-system.spec.js` pass.

- [ ] **Step 5: Commit documentation and validation changes**

```bash
git add README.md docs/BRANDBOOK.md tests/test_brand_assets.py tests/e2e/brand-system.spec.js
git commit -m "docs: publish Mass Sender brandbook"
```

## Plan Self-Review

- **Spec coverage:** Tasks 1 and 4 deliver all logo formats; Task 2 implements every token and typography rule; Task 3 applies the approved hierarchy; Task 5 documents app, marketing and social use.
- **No open placeholders:** confirmed.
- **Type consistency:** every template selector introduced in Task 3 is defined in Task 2 and asserted by Task 3 browser tests.
- **Review focus coverage:** Task 3 covers missing-image fallback, central masthead, mobile overflow, and campaign controls; Task 4 covers source whitespace/export size.
