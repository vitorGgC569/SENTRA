"""Offline enrollment in real Edge plus encrypted consent/rollback contracts."""
from __future__ import annotations

import json
import threading
from unittest.mock import Mock

import pytest

from sentra_remote import openai_auto_setup as auto
from sentra_remote import openai_browser_enrollment as en
from sentra_remote.product import ProductPaths, configure_tunnel, load_tunnel_config

KEY = "sk-proj_SYNTHETIC_new_0123456789abcdefghijklmnopqrstuvwxyz"
OLD = "sk-proj_SYNTHETIC_old_0123456789abcdefghijklmnopqrstuvwxyz"
TUNNEL = "tunnel_NEW0123456789abcdefghijkl"


@pytest.fixture
def paths(tmp_path):
    return ProductPaths(tmp_path / "install", tmp_path / "state")


def test_installer_consent_is_encrypted_bound_and_single_use(paths):
    auto.authorize_installer_enrollment(paths)
    encrypted = (paths.state_dir / "openai-enrollment-consent").read_text()
    assert str(paths.install_dir) not in encrypted
    assert "All" not in encrypted
    assert not auto.consume_installer_enrollment(ProductPaths(paths.install_dir / "other", paths.state_dir))
    auto.authorize_installer_enrollment(paths)
    assert auto.consume_installer_enrollment(paths)
    assert not auto.consume_installer_enrollment(paths)


def test_expired_or_corrupt_consent_does_not_authorize(paths, monkeypatch):
    auto.authorize_installer_enrollment(paths)
    monkeypatch.setattr(auto.time, "time", lambda: float("inf"))
    assert not auto.consume_installer_enrollment(paths)


def test_plaintext_cannot_impersonate_encrypted_installer_consent(paths):
    paths.state_dir.mkdir(parents=True)
    (paths.state_dir / "openai-enrollment-consent").write_text(json.dumps({
        "version": 1, "permissions": "All", "install_dir": str(paths.install_dir.resolve()),
        "expires": auto.time.time() + 1800,
    }))
    assert not auto.consume_installer_enrollment(paths)
    (paths.state_dir / "openai-enrollment-consent").write_text("invalid")
    assert not auto.consume_installer_enrollment(paths)


def runtime(*, ready=True, running=False):
    obj = Mock()
    obj.stop.return_value = True
    obj.status.return_value = {"tunnel": {"ok": running}}
    obj.connect_and_verify.return_value = {
        "chatgpt_onboarding": {"ready": ready},
        "status": {"mcp": {"ok": ready}, "tunnel": {"ok": ready}},
    }
    return obj


def test_success_requires_authenticated_tunnel_and_keeps_only_ciphertext(paths):
    verdict = auto.configure_and_verify(paths, TUNNEL, KEY, runtime())
    assert verdict == {"ok": True, "tunnel_verified": True}
    assert load_tunnel_config(paths, reveal_secret=True)["runtime_key"] == KEY
    assert KEY not in paths.tunnel_config.read_text()
    assert not (paths.state_dir / "tunnel.json.enrollment-rollback").exists()


@pytest.mark.parametrize("prior", [False, True])
def test_failure_restores_exact_prior_configuration(paths, prior):
    if prior:
        configure_tunnel(paths, "tunnel_PREVIOUS0123456789", OLD)
    original = paths.tunnel_config.read_bytes() if prior else None
    obj = runtime(ready=False, running=prior)
    result = auto.configure_and_verify(paths, TUNNEL, KEY, obj)
    assert not result["ok"] and result["rollback_restored"]
    assert (paths.tunnel_config.read_bytes() if paths.tunnel_config.exists() else None) == original
    assert KEY not in repr(result)
    assert obj.stop.call_count == 2


def test_false_ready_does_not_hide_unhealthy_mcp(paths):
    obj = runtime()
    obj.connect_and_verify.return_value["status"]["mcp"]["ok"] = False
    assert not auto.configure_and_verify(paths, TUNNEL, KEY, obj)["ok"]
    assert not paths.tunnel_config.exists()


def test_failed_recovery_keeps_encrypted_backup(paths):
    configure_tunnel(paths, "tunnel_PREVIOUS0123456789", OLD)
    obj = runtime(ready=False, running=True)
    obj.status.side_effect = [{"tunnel": {"ok": True}}, {"tunnel": {"ok": False}}]
    result = auto.configure_and_verify(paths, TUNNEL, KEY, obj)
    assert not result["rollback_restored"] and result["manual_recovery_available"]
    backup = (paths.state_dir / "tunnel.json.enrollment-rollback").read_text()
    assert OLD not in backup and KEY not in backup
    result = auto.configure_and_verify(paths, TUNNEL, KEY, obj)
    assert not result["ok"] and result["reason"] == "manual_recovery_required"


def test_refusing_to_stop_live_tunnel_leaves_prior_key(paths):
    configure_tunnel(paths, "tunnel_PREVIOUS0123456789", OLD)
    original = paths.tunnel_config.read_bytes()
    obj = runtime(running=True)
    obj.stop.return_value = False
    assert not auto.configure_and_verify(paths, TUNNEL, KEY, obj)["ok"]
    assert paths.tunnel_config.read_bytes() == original
    obj.connect_and_verify.assert_not_called()


def test_installer_consent_skips_desktop_confirmation(paths, monkeypatch):
    from sentra_remote import desktop
    from tkinter import messagebox
    auto.authorize_installer_enrollment(paths)
    prompt = Mock(return_value=False)
    monkeypatch.setattr(messagebox, "askyesno", prompt)
    browser = Mock()
    constructor = Mock(return_value=browser)
    monkeypatch.setattr(en, "OpenAIConsentBrowser", constructor)
    monkeypatch.setattr(desktop.threading, "Thread", lambda *, target, **kw: Mock(start=target))
    window = object.__new__(desktop.SentraDesktop)
    window.paths = paths
    window.tk = Mock()
    window.ttk = Mock()
    window.root = Mock()
    window.runtime = Mock()
    from sentra_remote.product import ProductSettings
    window.settings = ProductSettings(autostart_mcp=False, autostart_relay=False, autostart_tunnel=False)
    window.start_openai_browser_enrollment()
    prompt.assert_not_called()
    browser.start.assert_called_once_with(approved=True, automatic=True)
    assert constructor.call_count == 1
    assert constructor.call_args.args[0] == paths
    assert callable(constructor.call_args.args[1])
    assert constructor.call_args.kwargs == {"runtime": window.runtime}
    assert window.settings.autostart_mcp and window.settings.autostart_relay and window.settings.autostart_tunnel


def test_recovery_reuses_saved_candidate_after_crash_without_rotating(paths, monkeypatch):
    configure_tunnel(paths, TUNNEL, KEY)
    saved = paths.tunnel_config.read_bytes()
    backup = paths.tunnel_config.with_name("tunnel.json.enrollment-rollback")
    backup.write_bytes(b"")
    obj = runtime()
    configure = Mock(side_effect=AssertionError("must not create credentials"))
    monkeypatch.setattr(auto, "configure_tunnel", configure)
    result = auto.recover_enrollment(paths, obj)
    assert result["ok"] and result["credentials_reused"]
    assert paths.tunnel_config.read_bytes() == saved
    assert not backup.exists()
    configure.assert_not_called()
    obj.stop.assert_not_called()
    obj.connect_and_verify.assert_called_once_with(timeout_s=30.0)
    assert KEY not in repr(result)


def test_recovery_restores_exact_encrypted_backup_then_verifies(paths):
    configure_tunnel(paths, "tunnel_PREVIOUS0123456789", OLD)
    original = paths.tunnel_config.read_bytes()
    backup = paths.tunnel_config.with_name("tunnel.json.enrollment-rollback")
    backup.write_bytes(original)
    configure_tunnel(paths, TUNNEL, KEY)
    obj = runtime(running=True)
    obj.connect_and_verify.side_effect = [runtime(ready=False).connect_and_verify(),
                                         runtime().connect_and_verify()]
    result = auto.recover_enrollment(paths, obj)
    assert result["ok"] and result["rollback_restored"] and result["credentials_reused"]
    assert paths.tunnel_config.read_bytes() == original
    assert not backup.exists()
    obj.stop.assert_called_once_with("tunnel")
    assert obj.connect_and_verify.call_count == 2
    assert KEY not in repr(result) and OLD not in repr(result)


def test_recovery_from_crash_before_configure_with_no_previous_credentials(paths):
    paths.state_dir.mkdir()
    backup = paths.tunnel_config.with_name("tunnel.json.enrollment-rollback")
    backup.write_bytes(b"")
    obj = runtime()
    assert auto.recover_enrollment(paths, obj) == {"ok": False, "enrollment_needed": True}
    assert not backup.exists()
    obj.connect_and_verify.assert_not_called()


@pytest.mark.parametrize("backup_bytes", [b"", b"invalid", b"[]", json.dumps({
    "tunnel_id": TUNNEL, "runtime_key": OLD,
}).encode()])
def test_failed_candidate_never_uses_unsafe_backup_or_allows_new_creation(paths, backup_bytes):
    configure_tunnel(paths, TUNNEL, KEY)
    saved = paths.tunnel_config.read_bytes()
    backup = paths.tunnel_config.with_name("tunnel.json.enrollment-rollback")
    backup.write_bytes(backup_bytes)
    obj = runtime(ready=False)
    result = auto.recover_enrollment(paths, obj)
    assert result == {"ok": False, "reason": "manual_recovery_required"}
    assert backup.read_bytes() == backup_bytes
    assert paths.tunnel_config.read_bytes() == saved
    obj.stop.assert_not_called()


def test_recovery_failure_retains_backup_and_does_not_leak_runtime_exception(paths, capsys):
    configure_tunnel(paths, TUNNEL, OLD)
    original = paths.tunnel_config.read_bytes()
    backup = paths.tunnel_config.with_name("tunnel.json.enrollment-rollback")
    backup.write_bytes(original)
    configure_tunnel(paths, TUNNEL, KEY)
    obj = runtime()
    obj.connect_and_verify.side_effect = RuntimeError(KEY)
    result = auto.recover_enrollment(paths, obj)
    assert not result["ok"] and not result.get("enrollment_needed")
    assert backup.read_bytes() == original
    assert paths.tunnel_config.read_bytes() == original
    assert KEY not in repr(result) and OLD not in repr(result)
    assert capsys.readouterr() == ("", "")


def test_recovery_is_serialized_with_key_rotation(paths):
    from sentra_remote.product import tunnel_key_update
    locked, release = threading.Event(), threading.Event()
    def update():
        with tunnel_key_update(paths):
            locked.set()
            release.wait(5)
    thread = threading.Thread(target=update)
    thread.start()
    assert locked.wait(2)
    try:
        obj = runtime()
        result = auto.recover_enrollment(paths, obj)
        assert not result["ok"] and not result.get("enrollment_needed")
        obj.connect_and_verify.assert_not_called()
    finally:
        release.set()
        thread.join(2)


def test_retry_of_incomplete_configure_reuses_credentials_instead_of_overwriting(paths, monkeypatch):
    configure_tunnel(paths, TUNNEL, OLD)
    saved = paths.tunnel_config.read_bytes()
    backup = paths.tunnel_config.with_name("tunnel.json.enrollment-rollback")
    backup.write_bytes(b"")
    configure = Mock(side_effect=AssertionError("must not rotate an already saved credential"))
    monkeypatch.setattr(auto, "configure_tunnel", configure)
    result = auto.configure_and_verify(paths, TUNNEL, KEY, runtime())
    assert result["ok"] and result["credentials_reused"]
    assert paths.tunnel_config.read_bytes() == saved
    assert not backup.exists()
    configure.assert_not_called()


def test_saved_credentials_without_rollback_are_reused_on_retry(paths):
    configure_tunnel(paths, TUNNEL, KEY)
    obj = runtime(ready=False)
    first = auto.recover_enrollment(paths, obj)
    assert not first["ok"] and not first.get("enrollment_needed")
    obj.connect_and_verify.return_value = runtime().connect_and_verify()
    second = auto.recover_enrollment(paths, obj)
    assert second["ok"] and second["credentials_reused"]
    assert load_tunnel_config(paths, reveal_secret=True)["runtime_key"] == KEY
    obj.stop.assert_not_called()


@pytest.mark.parametrize("failure", ["mcp", "tunnel", "reauth"])
def test_recovery_never_commits_partial_or_unauthenticated_readiness(paths, failure):
    configure_tunnel(paths, TUNNEL, KEY)
    backup = paths.tunnel_config.with_name("tunnel.json.enrollment-rollback")
    backup.write_bytes(b"")
    obj = runtime()
    status = obj.connect_and_verify.return_value["status"]
    if failure == "reauth":
        status["tunnel"]["reauth_required"] = True
    else:
        status[failure]["ok"] = False
    result = auto.recover_enrollment(paths, obj)
    assert not result["ok"] and not result.get("enrollment_needed")
    assert backup.exists()


def test_recovery_preserves_candidate_if_live_tunnel_refuses_stop(paths):
    configure_tunnel(paths, TUNNEL, OLD)
    backup = paths.tunnel_config.with_name("tunnel.json.enrollment-rollback")
    backup.write_bytes(paths.tunnel_config.read_bytes())
    configure_tunnel(paths, TUNNEL, KEY)
    saved = paths.tunnel_config.read_bytes()
    obj = runtime(ready=False, running=True)
    obj.stop.return_value = False
    assert not auto.recover_enrollment(paths, obj)["ok"]
    assert paths.tunnel_config.read_bytes() == saved
    assert backup.exists()
    obj.connect_and_verify.assert_called_once()


def test_rotation_rollback_blocks_browser_preflight_without_touching_credentials(paths):
    configure_tunnel(paths, TUNNEL, KEY)
    saved = paths.tunnel_config.read_bytes()
    marker = paths.tunnel_config.with_name("tunnel.json.rotation-rollback")
    marker.write_bytes(saved)
    obj = runtime()
    result = auto.recover_enrollment(paths, obj)
    assert not result["ok"] and not result.get("enrollment_needed")
    assert marker.read_bytes() == saved and paths.tunnel_config.read_bytes() == saved
    obj.connect_and_verify.assert_not_called()


def test_unreadable_protected_credentials_never_reach_runtime_or_browser(paths, monkeypatch):
    configure_tunnel(paths, TUNNEL, KEY)
    backup = paths.tunnel_config.with_name("tunnel.json.enrollment-rollback")
    backup.write_bytes(paths.tunnel_config.read_bytes())
    monkeypatch.setattr(auto, "unprotect_secret", Mock(side_effect=RuntimeError(KEY)))
    obj = runtime()
    result = auto.recover_enrollment(paths, obj)
    assert not result["ok"] and not result.get("enrollment_needed")
    assert backup.exists() and KEY not in repr(result)
    obj.connect_and_verify.assert_not_called()


@pytest.mark.parametrize("ready", [True, False])
def test_desktop_preflight_never_opens_browser_when_credentials_exist(paths, monkeypatch, ready):
    from sentra_remote import desktop
    from tkinter import messagebox
    from sentra_remote.product import ProductSettings
    configure_tunnel(paths, TUNNEL, KEY)
    auto.authorize_installer_enrollment(paths)
    constructor = Mock()
    monkeypatch.setattr(messagebox, "askyesno", Mock(side_effect=AssertionError("consent already granted")))
    monkeypatch.setattr(en, "OpenAIConsentBrowser", constructor)
    monkeypatch.setattr(desktop.threading, "Thread", lambda *, target, **kw: Mock(start=target))
    window = object.__new__(desktop.SentraDesktop)
    window.paths, window.runtime = paths, runtime(ready=ready)
    window.tk, window.ttk, window.root = Mock(), Mock(), Mock()
    window.settings = ProductSettings()
    window.start_openai_browser_enrollment()
    constructor.return_value.start.assert_not_called()
    window.runtime.connect_and_verify.assert_called_once_with(timeout_s=30.0)


def test_deep_link_alone_cannot_start_browser_without_consent(paths, monkeypatch):
    from sentra_remote import desktop
    from tkinter import messagebox
    prompt = Mock(return_value=False)
    constructor = Mock()
    monkeypatch.setattr(messagebox, "askyesno", prompt)
    monkeypatch.setattr(en, "OpenAIConsentBrowser", constructor)
    window = object.__new__(desktop.SentraDesktop)
    window.paths = paths
    window.start_openai_browser_enrollment()
    prompt.assert_called_once()
    constructor.assert_not_called()


@pytest.mark.parametrize("change", ["tunnel", "port", "key_reference", "invalid"])
def test_managed_profile_regenerates_for_changed_tunnel_or_mcp(paths, monkeypatch, change):
    import yaml
    from sentra_remote.local_runtime import LocalRuntime
    from sentra_remote.product import ProductSettings
    obj = object.__new__(LocalRuntime)
    obj.paths, obj.settings = paths, ProductSettings()
    profile = paths.tunnel_dir / "profiles" / "sentra-local.yaml"
    profile.parent.mkdir(parents=True)
    data = {"control_plane": {"tunnel_id": TUNNEL, "api_key": "env:CONTROL_PLANE_API_KEY"},
            "mcp": {"server_urls": [{"channel": "main", "url": "http://127.0.0.1:8000/mcp"}]}}
    profile.write_text(yaml.safe_dump(data))
    command = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr("sentra_remote.local_runtime.subprocess.run", command)
    obj._init_tunnel_profile(KEY, TUNNEL)
    command.assert_not_called()
    if change == "tunnel":
        data["control_plane"]["tunnel_id"] = "tunnel_PREVIOUS0123456789"
    elif change == "port":
        obj.settings.mcp_port = 8123
    elif change == "key_reference":
        data["control_plane"]["api_key"] = "file:legacy-secret"
    profile.write_text("[broken" if change == "invalid" else yaml.safe_dump(data))
    obj._init_tunnel_profile(KEY, TUNNEL)
    command.assert_called_once()
    args = command.call_args.args[0]
    assert TUNNEL in args
    assert f"http://127.0.0.1:{obj.settings.mcp_port}/mcp" in args
    assert KEY not in repr(args)


def test_profile_init_failure_never_returns_cli_secret(paths, monkeypatch):
    from sentra_remote.local_runtime import LocalRuntime
    from sentra_remote.product import ProductSettings
    obj = object.__new__(LocalRuntime)
    obj.paths, obj.settings = paths, ProductSettings()
    monkeypatch.setattr("sentra_remote.local_runtime.subprocess.run",
                        Mock(return_value=Mock(returncode=1, stderr=KEY)))
    with pytest.raises(RuntimeError, match="tunnel_profile_initialization_failed") as error:
        obj._init_tunnel_profile(KEY, TUNNEL)
    assert KEY not in str(error.value)


def test_background_supervisor_waits_for_key_update(paths):
    from sentra_remote.local_runtime import LocalRuntime
    from sentra_remote.product import tunnel_key_update
    obj = object.__new__(LocalRuntime)
    obj.paths, obj._tunnel_restart_attempts = paths, 0
    obj._supervise_tunnel_once = Mock()
    locked, release = threading.Event(), threading.Event()
    def update():
        with tunnel_key_update(paths):
            locked.set()
            release.wait(4)
    thread = threading.Thread(target=update)
    thread.start()
    assert locked.wait(2)
    try:
        assert obj.supervise_once()["state"] == "CONFIGURING"
        obj._supervise_tunnel_once.assert_not_called()
    finally:
        release.set()
        thread.join(2)


@pytest.mark.parametrize("message", [
    "Não foi possível verificar automaticamente a associação entre esses workspaces e as organizações.",
    "We couldn't automatically verify the association between these workspaces and organizations.",
])
def test_platform_association_failure_stops_enrollment_before_creation(message):
    page = Mock(url=en.OPENAI_TUNNELS_URL)
    page.is_closed.return_value = False
    problem = Mock()
    problem.count.return_value = 1
    problem.first.is_visible.return_value = True
    page.get_by_text.return_value = problem
    probe = Mock()
    with pytest.raises(ValueError, match="workspace_association_unverified"):
        auto.AutomaticEnrollment(page, lambda *_: None, threading.Event()).wait(probe, kind="tunnel")
    assert page.get_by_text.call_args.args[0].search(message)
    probe.assert_not_called()


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
        except Exception as exc:
            if "Executable doesn't exist" in str(exc):
                pytest.skip("Edge unavailable")
            raise
        try:
            yield browser.new_page()
        finally:
            browser.close()


def install_fixture(page, *, existing=(), all_permissions=True):
    tunnels = """<main>EXISTING</main><button onclick="openTunnel()">Create tunnel</button>
    <script>
    function openTunnel() {
      document.body.insertAdjacentHTML('beforeend', `<section role="dialog">
        <label>Name <input id="name"></label><button onclick="createTunnel()">Create</button></section>`);
    }
    function createTunnel() {
      window.tunnelCreates = (window.tunnelCreates || 0) + 1;
      document.querySelector('main').insertAdjacentHTML('beforeend', '<code>NEWID</code>');
      document.querySelector('[role=dialog]').remove();
    }
    </script>""".replace("EXISTING", "".join(f"<code>{item}</code>" for item in existing)).replace("NEWID", TUNNEL)
    keys = """<button onclick="openKey()">Create new secret key</button><script>
    function openKey() {
      document.body.insertAdjacentHTML('beforeend', `<section role="dialog">
      <label>Name <input id="name"></label>
      <label><input type="radio" name="permissions" value="Restricted" checked>Restricted</label>
      ALLRADIO
      <button onclick="createKey()">Create secret key</button></section>`);
    }
    function createKey() {
      window.keyCreates = (window.keyCreates || 0) + 1;
      window.createdPermission = document.querySelector('input[name=permissions]:checked').value;
      document.querySelector('[role=dialog]').innerHTML = '<span>SECRET</span>';
    }
    </script>""".replace("SECRET", KEY).replace("ALLRADIO", (
        '<label><input type="radio" name="permissions" value="All">All</label>' if all_permissions else ""
    ))
    def route(request):
        url = request.request.url
        if url == en.OPENAI_TUNNELS_URL:
            request.fulfill(body=tunnels, content_type="text/html")
        elif url == en.OPENAI_API_KEYS_URL:
            request.fulfill(body=keys, content_type="text/html")
        else:
            request.abort()
    page.route("**/*", route)
    page.goto(en.OPENAI_TUNNELS_URL)


@pytest.mark.parametrize("existing", [(), ("tunnel_OLD0123456789",), ("tunnel_OLD0123456789", "tunnel_OTHER0123456789")])
def test_real_edge_creation_all_capture_and_verified_storage(page, paths, existing):
    install_fixture(page, existing=existing)
    events = []
    tunnel, key = auto.AutomaticEnrollment(page, lambda *args: events.append(args), threading.Event()).run()
    assert tunnel == TUNNEL
    assert key == KEY
    assert page.evaluate("window.createdPermission") == "All"
    assert page.evaluate("window.keyCreates") == 1
    assert KEY not in repr(events)
    assert auto.configure_and_verify(paths, tunnel, key, runtime())["ok"]
    assert KEY not in paths.tunnel_config.read_text()


def test_missing_all_never_submits_key_creation(page):
    install_fixture(page, existing=(TUNNEL,), all_permissions=False)
    with pytest.raises(ValueError, match="all_permissions_unavailable"):
        auto.AutomaticEnrollment(page, lambda *_: None, threading.Event(),
                                 existing_tunnel_id=TUNNEL).run()
    assert page.evaluate("window.keyCreates || 0") == 0


def test_reuses_only_previously_configured_sentra_tunnel(page):
    old = "tunnel_OLD0123456789"
    install_fixture(page, existing=(old, "tunnel_OTHER0123456789"))
    tunnel, key = auto.AutomaticEnrollment(
        page, lambda *_: None, threading.Event(), existing_tunnel_id=old,
    ).run()
    assert tunnel == old and key == KEY


def test_cancelled_or_hostile_page_blocks_click(page):
    install_fixture(page)
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(RuntimeError, match="enrollment_cancelled"):
        auto.AutomaticEnrollment(page, lambda *_: None, cancelled).run()
    assert page.evaluate("window.tunnelCreates || 0") == 0
    page.route("https://evil.invalid/**", lambda route: route.fulfill(body="<button>Create</button>"))
    page.goto("https://evil.invalid/settings/organization/api-keys")
    with pytest.raises(ValueError, match="open_official_api_keys_page"):
        auto.AutomaticEnrollment(page, lambda *_: None, threading.Event()).click(page, "Create", "key")
