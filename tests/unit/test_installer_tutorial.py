from pathlib import Path
import shutil
from unittest.mock import Mock
from sentra_remote import installer


def test_frozen_setup_opens_bundled_tutorial_before_install(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    docs = Path(installer.__file__).resolve().parents[1] / "docs"
    extracted = tmp_path / "extracted"
    shutil.copytree(docs / "onboarding_media", extracted / "docs/onboarding_media")
    monkeypatch.setattr(installer.sys, "frozen", True, raising=False)
    monkeypatch.setattr(installer.sys, "_MEIPASS", str(extracted), raising=False)
    opened = Mock(return_value=True)
    monkeypatch.setattr("webbrowser.open", opened)
    monkeypatch.setattr("tkinter.messagebox.showerror", Mock())
    wizard = object.__new__(installer.InstallerWizard)
    wizard._open_setup_tutorial()
    opened.assert_called_once()
    from urllib.parse import urlparse, unquote
    import urllib.request
    cached = Path(urllib.request.url2pathname(unquote(urlparse(opened.call_args.args[0]).path)))
    assert cached.is_relative_to(tmp_path / "local/SENTRA/Tutorials")
    shutil.rmtree(extracted)
    assert cached.is_file()
    assert (cached.parent / "mcp-create-tunnel.mp4").is_file()
    assert (cached.parent / "mcp-connect-connector.mp4").is_file()
    assert not (tmp_path / "Commander").exists()


def test_incomplete_tutorial_reports_error_without_opening(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "docs_source", lambda:tmp_path)
    opened = Mock()
    failure = Mock()
    monkeypatch.setattr("webbrowser.open", opened)
    monkeypatch.setattr("tkinter.messagebox.showerror", failure)
    object.__new__(installer.InstallerWizard)._open_setup_tutorial()
    opened.assert_not_called()
    failure.assert_called_once()


def test_current_guide_matches_full_permissions_and_explains_authentication():
    guide = (installer.docs_source() / "onboarding_media/SENTRA_SETUP_GUIDE.html").read_text(encoding="utf-8")
    assert "PERMISSÕES ALL" in guide
    assert "PERMISSÕES MÍNIMAS" not in guide
    assert "Codex CLI instalado e autenticado" in guide
    assert "instruções em texto" in guide
