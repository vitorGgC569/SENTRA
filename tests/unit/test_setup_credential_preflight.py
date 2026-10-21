"""Credential failures must preserve installed bytes before Setup can mutate."""
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sentra_remote import installer, openai_auto_setup as auto


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("mode", ["exception", "mismatch"])
def test_storage_failure_preserves_installation_and_prevents_downloads(tmp_path, monkeypatch, existing, mode):
    root = tmp_path / "installed"
    state = tmp_path / "state"
    if existing:
        root.mkdir()
        installer._write_install_marker(root)
        (root / "sentra-canvas.exe").write_bytes(b"previous executable")
        state.mkdir()
        (state / "tunnel.json").write_bytes(b"previous encrypted configuration")
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    monkeypatch.setattr(installer, "check_install_payload", lambda _: {"ok": True})
    mutation = Mock(side_effect=AssertionError("no installation effects"))
    monkeypatch.setattr(installer, "prepare_tunnel_archive", mutation)
    monkeypatch.setattr(installer, "_install_product", mutation)
    monkeypatch.setattr(auto, "protect_secret", Mock(side_effect=OSError("private diagnostic")) if mode == "exception" else lambda _: "ciphertext")
    monkeypatch.setattr(auto, "unprotect_secret", lambda _: "different value")
    with pytest.raises(auto.CredentialProtectionUnavailable) as error:
        installer.install(install_dir=root, state_dir=state)
    assert str(error.value) == "credential_protection_unavailable"
    mutation.assert_not_called()
    for name, content in before.items():
        assert (tmp_path / name).read_bytes() == content
    assert root.exists() == existing
    assert not (state / "installer-progress.json").exists()


def test_offline_update_defers_credential_check_until_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "check_install_payload", lambda _: {"ok": True})
    monkeypatch.setattr(installer, "prepare_tunnel_archive", lambda *_: tmp_path / "archive")
    probe = Mock(side_effect=AssertionError("offline update must remain quiesced"))
    monkeypatch.setattr(auto, "verify_credential_protection", probe)
    apply = Mock(return_value={"connect_verify": {"deferred": "post_update_restart"}})
    monkeypatch.setattr(installer, "_install_product", apply)
    handoff = tmp_path / "handoff.json"
    installer.install(install_dir=tmp_path / "installed", state_dir=tmp_path / "state", offline_handoff=handoff)
    probe.assert_not_called()
    assert apply.call_args.kwargs["offline_handoff"] == handoff


def test_silent_failure_has_fixed_evidence_without_private_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "check_install_payload", lambda _: {"ok": True})
    monkeypatch.setattr(auto, "protect_secret", Mock(side_effect=OSError("private diagnostic")))
    report = tmp_path / "report.json"
    assert installer.main(["--silent", "--install-dir", str(tmp_path / "installed"),
                           "--state-dir", str(tmp_path / "state"), "--report-file", str(report)]) == 2
    raw = report.read_text()
    evidence = json.loads(raw)
    assert evidence["preflight_failure"] == "credential_protection_unavailable"
    assert not evidence["ready"] and not evidence["homologated"]
    assert not evidence["browser_enrollment"]["attempted"]
    diagnostic = (tmp_path / "state/installer-error.json").read_text()
    assert "private diagnostic" not in raw + diagnostic
    assert not (tmp_path / "installed").exists()


@pytest.mark.parametrize("mismatch", [False, True])
def test_disposable_keyring_entry_is_removed_even_after_failed_readback(monkeypatch, mismatch):
    values = {}
    def protect(value):
        values["probe"] = value
        return "keyring:owned-test-entry"
    monkeypatch.setattr(auto, "protect_secret", protect)
    monkeypatch.setattr(auto, "unprotect_secret", lambda _: "different" if mismatch else values["probe"])
    delete = Mock()
    monkeypatch.setitem(sys.modules, "keyring", SimpleNamespace(delete_password=delete))
    if mismatch:
        with pytest.raises(auto.CredentialProtectionUnavailable):
            auto.verify_credential_protection()
    else:
        auto.verify_credential_protection()
    delete.assert_called_once_with("SENTRA Commander", "owned-test-entry")
