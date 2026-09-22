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


def test_brand_tokens_and_primitives_are_declared():
    css = Path("static/styles.css").read_text(encoding="utf-8")
    for token in ("--brand-signal: #2BCAC2", "--semantic-success: #C5FF64", "--font-display"):
        assert token in css
    for selector in (".brand-masthead", ".brand-product-lockup", ".brand-logo-fallback"):
        assert selector in css
