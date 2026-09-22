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
