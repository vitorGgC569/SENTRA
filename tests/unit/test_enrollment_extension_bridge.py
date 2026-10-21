"""Transport, tab ownership, install ownership and no-profile-copy boundaries."""
import io
import json
import socket
import struct
import threading
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sentra_remote import enrollment_bridge as bridge
from sentra_remote import enrollment_extension as extension
from sentra_remote import enrollment_native as native


def test_frames_support_partial_reads_and_utf8():
    output = io.BytesIO()
    bridge.write_frame(output, {"value": "configuração"})
    class Partial(io.BytesIO):
        def read(self, size=-1): return super().read(min(size, 2))
    stream = Partial(output.getvalue())
    assert bridge.read_frame(stream) == {"value": "configuração"}
    assert bridge.read_frame(stream) is None


@pytest.mark.parametrize("data", [b"\x01", struct.pack("<I", 0), struct.pack("<I", bridge.MAX_MESSAGE + 1),
    struct.pack("<I", 4), struct.pack("<I", 4) + b"null", struct.pack("<I", 2) + b"[]"])
def test_invalid_frames_are_rejected_without_diagnostics(data):
    with pytest.raises(ValueError): bridge.read_frame(io.BytesIO(data))


@pytest.fixture
def protected(monkeypatch):
    # Unit-only reversible stand-in. Actual DPAPI remains a separate VM test.
    from sentra_remote import secrets
    monkeypatch.setattr(secrets, "protect_secret", lambda value: "dpapi:" + value)
    monkeypatch.setattr(secrets, "unprotect_secret", lambda value: value.removeprefix("dpapi:"))


def connect(broker, *, secret=None, family="firefox", preferred=True):
    connection = socket.create_connection(("127.0.0.1", broker.server.getsockname()[1]))
    channel = connection.makefile("rwb", buffering=0)
    bridge.write_frame(channel, {"protocol": 1, "secret": broker.secret if secret is None else secret,
                                 "family": family, "platform_tab": preferred})
    return connection, channel


def test_real_socket_rpc_does_not_relay_arbitrary_script_and_owns_only_created_tab(tmp_path, protected):
    paths = SimpleNamespace(state_dir=tmp_path)
    requests = []
    with bridge.EnrollmentBridge(paths) as broker:
        connection, channel = connect(broker)
        def browser():
            while True:
                command = bridge.read_frame(channel)
                if command is None: return
                requests.append(command)
                results = {"open": 42, "url": "https://platform.openai.com/settings/organization/tunnels", "close": True}
                bridge.write_frame(channel, {"id": command["id"], "ok": True, "result": results[command["operation"]]})
        thread = threading.Thread(target=browser, daemon=True); thread.start()
        context = broker.context(timeout=1)
        assert context.browser_name == "firefox"
        page = context.new_page()
        assert page.url.endswith("/tunnels")
        with pytest.raises(ValueError, match="arbitrary_script_forbidden"):
            page.evaluate("() => document.cookie")
        context.close()
        assert requests[-1] == {"id": 3, "operation": "close", "tab": 42}
    thread.join(timeout=2)
    channel.close(); connection.close()
    assert not bridge.descriptor_path(tmp_path).exists()


def test_bad_capability_never_enrolls_a_browser(tmp_path, protected):
    with bridge.EnrollmentBridge(SimpleNamespace(state_dir=tmp_path)) as broker:
        connection, channel = connect(broker, secret="wrong")
        assert broker.context(timeout=0.1) is None
        channel.close(); connection.close()


def test_initial_tunnel_navigation_is_not_reissued_but_key_navigation_is():
    from sentra_remote.onboarding import OPENAI_TUNNELS_URL, OPENAI_API_KEYS_URL
    requests = []

    class Client:
        browser_name = "chromium"
        def request(self, operation, **payload):
            requests.append((operation, payload))
            return 42 if operation == "open" else True

    context = bridge.ExtensionEnrollmentContext(Client())
    page = context.new_page()
    # open has already issued tabs.update; do not cancel its pending navigation.
    page.goto(OPENAI_TUNNELS_URL)
    assert [operation for operation, _ in requests] == ["open"]
    page.goto(OPENAI_API_KEYS_URL)
    assert requests[-1][0] == "navigate"
    assert requests[-1][1]["url"] == OPENAI_API_KEYS_URL
    context.close()
    assert requests[-1] == ("close", {"tab": 42})


def test_explicit_second_tunnel_navigation_and_noninitial_targets_are_preserved():
    from sentra_remote.onboarding import OPENAI_TUNNELS_URL, OPENAI_API_KEYS_URL
    client = Mock()
    page = bridge.ExtensionPage(client, 12, initial_url=OPENAI_TUNNELS_URL)
    page.goto(OPENAI_TUNNELS_URL)
    client.request.assert_not_called()
    page.goto(OPENAI_TUNNELS_URL)
    client.request.assert_called_once_with("navigate", tab=12, url=OPENAI_TUNNELS_URL, timeout=32)
    client.reset_mock()
    bridge.ExtensionPage(client, 14, initial_url=OPENAI_TUNNELS_URL).goto(OPENAI_API_KEYS_URL)
    client.request.assert_called_once_with("navigate", tab=14, url=OPENAI_API_KEYS_URL, timeout=32)


def test_multiple_connected_profiles_are_not_guessed(tmp_path, protected):
    with bridge.EnrollmentBridge(SimpleNamespace(state_dir=tmp_path)) as broker:
        a, sa = connect(broker)
        b, sb = connect(broker, family="chromium")
        with pytest.raises(ValueError, match="browser_account_selection_required"):
            broker.context(timeout=1)
        sa.close(); sb.close(); a.close(); b.close()


def test_live_setup_cannot_be_replaced_and_owner_cleans_its_lease(tmp_path, protected):
    with bridge.EnrollmentBridge(SimpleNamespace(state_dir=tmp_path)):
        original = bridge.descriptor_path(tmp_path).read_text()
        with pytest.raises(RuntimeError, match="already_running"):
            with bridge.EnrollmentBridge(SimpleNamespace(state_dir=tmp_path)): pass
        assert bridge.descriptor_path(tmp_path).read_text() == original
    assert not bridge.descriptor_path(tmp_path).exists()


def test_native_stdio_to_authenticated_broker_round_trip(tmp_path, protected):
    statuses, operations, result = [], [], []
    native_end, browser_end = socket.socketpair()
    host_stream = native_end.makefile("rwb", buffering=0)
    browser_stream = browser_end.makefile("rwb", buffering=0)
    def host():
        result.append(native.transport(tmp_path, "firefox", host_stream, host_stream, idle_timeout=2))
    def browser():
        bridge.write_frame(browser_stream, {"protocol": 1, "platform_tab": True})
        while True:
            value = bridge.read_frame(browser_stream)
            if value is None: return
            if "status" in value:
                statuses.append(value["status"])
                continue
            operations.append(value["operation"])
            bridge.write_frame(browser_stream, {"id": value["id"], "ok": True,
                "result": 12 if value["operation"] == "open" else True})
    with bridge.EnrollmentBridge(SimpleNamespace(state_dir=tmp_path)) as broker:
        host_thread = threading.Thread(target=host, daemon=True); host_thread.start()
        browser_thread = threading.Thread(target=browser, daemon=True); browser_thread.start()
        context = broker.context(timeout=2)
        assert context.browser_name == "firefox"
        context.new_page(); context.close()
    host_thread.join(timeout=3)
    assert result == [0]
    assert statuses == ["waiting_for_setup", "connected"]
    assert operations == ["open", "close"]
    native_end.shutdown(socket.SHUT_RDWR); browser_end.shutdown(socket.SHUT_RDWR)
    host_stream.close(); browser_stream.close(); native_end.close(); browser_end.close()
    browser_thread.join(timeout=2)


def test_staging_builds_firefox_and_chromium_without_cookies_or_public_urls(tmp_path):
    extension.stage_extensions(Path(extension.__file__).parent / "enrollment_extension", tmp_path)
    firefox = json.loads((tmp_path / "firefox/manifest.json").read_text(encoding="utf-8"))
    chrome = json.loads((tmp_path / "chromium/manifest.json").read_text(encoding="utf-8"))
    assert firefox["background"] == {"scripts": ["background.js"]}
    assert chrome["background"] == {"service_worker": "background.js"}
    assert firefox["browser_specific_settings"]["gecko"]["id"] == bridge.FIREFOX_ID
    assert "cookies" not in firefox["permissions"]
    assert firefox["host_permissions"] == ["https://platform.openai.com/*"]
    assert "/*__EXTRACTORS__*/" not in (tmp_path / "firefox/dom.js").read_text()
    assert "eval(" not in (tmp_path / "firefox/dom.js").read_text()
    assert not json.loads((tmp_path / "distribution.json").read_text())["production_distribution_ready"]
    assert extension.verified_firefox_package(tmp_path / extension.FIREFOX_SIGNED_NAME).is_file()
    assert json.loads((tmp_path / "distribution.json").read_text())["firefox_channel"] == "unlisted"


def test_changed_signed_package_is_rejected_before_opening_a_browser(tmp_path):
    package = tmp_path / "browser-enrollment" / extension.FIREFOX_SIGNED_NAME
    package.parent.mkdir()
    package.write_bytes(b"not the Mozilla-approved package")
    launcher = Mock()
    with pytest.raises(ValueError, match="checksum"):
        extension.open_firefox_bridge_installation(tmp_path, popen=launcher)
    launcher.assert_not_called()


def test_changed_source_cannot_be_staged_with_an_older_signed_package(tmp_path):
    original = Path(extension.__file__).parent / "enrollment_extension"
    source = tmp_path / "source"
    source.mkdir()
    for name in ("background.js", "dom.js", extension.FIREFOX_SIGNED_NAME):
        shutil.copyfile(original / name, source / name)
    background = source / "background.js"
    background.write_text(background.read_text().replace("com.sentra.enrollment", "com.changed.enrollment"))
    with pytest.raises(ValueError, match="source_mismatch"):
        extension.stage_extensions(source, tmp_path / "staged")


def test_firefox_installation_handoff_preserves_normal_profile_and_browser_consent(tmp_path, monkeypatch):
    original = Path(extension.__file__).parent / "enrollment_extension"
    destination = tmp_path / "browser-enrollment"
    destination.mkdir()
    shutil.copyfile(original / extension.FIREFOX_SIGNED_NAME, destination / extension.FIREFOX_SIGNED_NAME)
    browser = tmp_path / "Firefox/firefox.exe"
    monkeypatch.setattr(extension, "_find_firefox", lambda: browser)
    launcher = Mock()
    result = extension.open_firefox_bridge_installation(tmp_path, popen=launcher)
    assert result["browser_opened"] is True
    commands = [call.args[0] for call in launcher.call_args_list]
    assert commands[0] == [str(browser), "about:addons"]
    assert commands[1][1:] == ["/select,", str((destination / extension.FIREFOX_SIGNED_NAME).resolve())]
    assert all(not any(flag in " ".join(command) for flag in ("-profile", "-marionette", "--load-extension", "--disable"))
               for command in commands)


def test_signed_artifact_bytes_invalidate_the_build_source_proof(tmp_path):
    from scripts.commander.build_windows import _source_fingerprint
    package = tmp_path / "sentra_remote/enrollment_extension/firefox-signed.xpi"
    package.parent.mkdir(parents=True)
    package.write_bytes(b"first artifact")
    before = _source_fingerprint(tmp_path)
    package.write_bytes(b"changed artifact")
    assert before != _source_fingerprint(tmp_path)


def test_setup_resumes_enrollment_after_the_browser_installation_handoff(tmp_path, monkeypatch):
    from sentra_remote.installer import InstallerWizard
    from tkinter import messagebox
    handoff = Mock()
    monkeypatch.setattr(extension, "open_firefox_bridge_installation", handoff)
    confirmation = Mock()
    monkeypatch.setattr(messagebox, "showinfo", confirmation)
    wizard = SimpleNamespace(install_dir=SimpleNamespace(get=lambda: str(tmp_path)), _start_browser_setup=Mock())
    InstallerWizard._open_firefox_bridge(wizard)
    handoff.assert_called_once_with(tmp_path.resolve())
    confirmation.assert_called_once()
    wizard._start_browser_setup.assert_called_once_with()


def test_native_host_authenticates_extension_id_and_manifest_location(tmp_path):
    assert native.caller_family([f"chrome-extension://{bridge.CHROMIUM_ID}/"], tmp_path) == "chromium"
    manifest = tmp_path / "browser-enrollment/native-firefox.json"
    assert native.caller_family([str(manifest), bridge.FIREFOX_ID], tmp_path) == "firefox"
    for args in (["chrome-extension://" + "a" * 32 + "/"], [str(tmp_path / "fake.json"), bridge.FIREFOX_ID],
                 [str(manifest), "another@extension"], []):
        with pytest.raises(PermissionError): native.caller_family(args, tmp_path)


def test_no_bridge_does_not_claim_reuse_or_launch_an_empty_browser(tmp_path, monkeypatch):
    from sentra_remote import browser_enrollment_session as sessions
    monkeypatch.setattr(sessions, "discover_browser_endpoints", lambda: [])
    playwright = Mock()
    with pytest.raises(ValueError, match="browser_extension_required"):
        sessions.enrollment_context(playwright, tmp_path, Mock())
    playwright.chromium.launch_persistent_context.assert_not_called()


class Registry:
    HKEY_CURRENT_USER = 1
    KEY_READ = 1
    KEY_QUERY_VALUE = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1
    def __init__(self): self.data = {}; self.writes = []
    def OpenKey(self, hive, name, *args):
        if name not in self.data: raise FileNotFoundError(name)
        return self.Key(name)
    def CreateKeyEx(self, hive, name, *args): return self.Key(name)
    def QueryValueEx(self, key, name):
        if key.name not in self.data: raise FileNotFoundError(key.name)
        return self.data[key.name], self.REG_SZ
    def SetValueEx(self, key, name, reserved, kind, value):
        self.writes.append(key.name); self.data[key.name] = value
    def DeleteKey(self, hive, name): del self.data[name]
    class Key:
        def __init__(self, name): self.name = name
        def __enter__(self): return self
        def __exit__(self, *args): pass


def test_native_registration_is_idempotent_and_uninstall_preserves_other_install(tmp_path):
    (tmp_path / "sentra-browser-relay.exe").write_bytes(b"fixture")
    (tmp_path / ".sentra-install.json").write_text("{}")
    registry = Registry()
    result = extension.register_native_host(tmp_path, tmp_path / "state", registry=registry)
    assert result["registered"] and len(registry.data) == len(extension.REGISTRY_ROOTS)
    extension.register_native_host(tmp_path, tmp_path / "state", registry=registry)
    firefox = json.loads((tmp_path / "browser-enrollment/native-firefox.json").read_text())
    assert firefox["allowed_extensions"] == [bridge.FIREFOX_ID]
    assert "allowed_origins" not in firefox
    preserved = next(iter(registry.data))
    registry.data[preserved] = str(tmp_path / "other-install/native-chromium.json")
    extension.unregister_native_host(tmp_path, registry=registry)
    assert list(registry.data) == [preserved]
    writes_before = len(registry.writes)
    with pytest.raises(RuntimeError, match="owned_by_other"):
        extension.register_native_host(tmp_path, tmp_path / "state", registry=registry)
    assert len(registry.writes) == writes_before
