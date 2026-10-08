from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
START_HERE = ROOT / "docs" / "START_HERE.md"


def test_start_here_documents_all_product_surfaces() -> None:
    text = START_HERE.read_text(encoding="utf-8")
    required = (
        "SENTRA Desktop",
        "sentra-cli",
        "Secure MCP Tunnel",
        "Codex + Web Models",
        "Plugin/extensão Edge",
        "Maestri + múltiplos SENTRAs",
    )
    for phrase in required:
        assert phrase in text


def test_start_here_has_one_tunnel_authority_and_lazy_optional_tools() -> None:
    text = START_HERE.read_text(encoding="utf-8")
    assert "SENTRA é a autoridade do tunnel" in text
    assert "não cria um segundo tunnel" in text
    assert "Git e Docker são opcionais" in text
    assert "Windows DPAPI" in text


def test_quickstart_links_to_start_here() -> None:
    quickstart = (ROOT / "docs" / "QUICKSTART.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "[START HERE](START_HERE.md)" in quickstart
    assert "docs/START_HERE.md" in readme


def test_release_packages_product_education_docs() -> None:
    release_script = (ROOT / "scripts" / "commander" / "release_assets.py").read_text(
        encoding="utf-8"
    )
    for name in (
        "START_HERE.md",
        "USING_SENTRA.md",
        "SENTRA_CLI.md",
        "WEB_MODELS.md",
        "MCP_SERVER.md",
    ):
        assert name in release_script
