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


def test_brand_has_ice_and_monochrome_lockups_for_marketing_contexts():
    for lockup in ("symbol", "horizontal", "stacked"):
        assert (BRAND / f"mass-sender-cofre-{lockup}-ice.svg").is_file()
        assert (BRAND / f"mass-sender-cofre-{lockup}-mono.svg").is_file()
        assert (BRAND / "png" / f"mass-sender-cofre-{lockup}-ice-2048.png").is_file()
        assert (BRAND / "png" / f"mass-sender-cofre-{lockup}-mono-2048.png").is_file()


def test_brand_tokens_and_primitives_are_declared():
    css = Path("static/styles.css").read_text(encoding="utf-8")
    for token in ("--brand-signal: #2BCAC2", "--semantic-success: #C5FF64", "--font-display"):
        assert token in css
    for selector in (".brand-masthead", ".brand-product-lockup", ".brand-logo-fallback"):
        assert selector in css


def test_png_export_inventory_is_complete():
    expected = {
        "mass-sender-cofre-symbol-512.png",
        "mass-sender-cofre-symbol-1024.png",
        "mass-sender-cofre-symbol-2048.png",
        "mass-sender-cofre-horizontal-512.png",
        "mass-sender-cofre-horizontal-1024.png",
        "mass-sender-cofre-horizontal-2048.png",
        "mass-sender-cofre-stacked-512.png",
        "mass-sender-cofre-stacked-1024.png",
        "mass-sender-cofre-stacked-2048.png",
        "daludi-logo-digital.png",
        "favicon-16.png",
        "favicon-32.png",
        "favicon-48.png",
        "favicon-180.png",
        "favicon-512.png",
    }
    actual = {path.name for path in (BRAND / "png").glob("*.png")}
    assert expected <= actual
    assert (Path("static") / "favicon.ico").is_file()


def test_readme_links_to_brandbook():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "docs/BRANDBOOK.md" in readme


def test_product_templates_expose_browser_favicon():
    for template_name in ("login.html", "index.html", "campaign.html", "agent_settings.html"):
        template = Path("templates") / template_name
        contents = template.read_text(encoding="utf-8")
        assert 'rel="icon"' in contents
        assert "/static/brand/png/favicon-32.png" in contents
