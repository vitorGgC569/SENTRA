"""Real Codex CLI + isolated MCP. Never changes the developer's Codex profile."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import pytest

from sentra_remote.codex_setup import configure_codex, find_codex


@pytest.mark.parametrize("component", ["host", "bundled"])
def test_real_codex_plugin_install_and_health(tmp_path, component):
    if component == "bundled":
        folder = Path(__file__).resolve().parents[2] / "dist/prerequisites/codex-registration"
        if not folder.exists():
            pytest.skip("Prepared offline Codex registration component is absent")
        from sentra_remote.codex_registration_runtime import validate_registration_runtime
        cli = validate_registration_runtime(folder)
    else:
        cli = find_codex()
    if cli is None:
        pytest.skip("Codex CLI not installed on this host")
    profile = tmp_path / "isolated-codex"
    profile.mkdir()
    config = profile / "config.toml"
    config.write_text('model = "custom-preserved-model"\n', encoding="utf-8")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    # Codex also discovers personal marketplaces from the user's home, not
    # only CODEX_HOME. Isolate both, otherwise a real plugin may shadow ours.
    env = dict(os.environ, CODEX_HOME=str(profile), USERPROFILE=str(tmp_path), HOME=str(tmp_path))
    if component == "bundled" and os.name == "nt":
        env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    with (tmp_path / "mcp.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([
            sys.executable, "-B", "-m", "sentra_mcp", "--transport", "streamable-http",
            "--host", "127.0.0.1", "--port", str(port), "--allowed-root", str(tmp_path),
            "--state-dir", str(tmp_path / "mcp-state"), "--audit-log", str(tmp_path / "audit.jsonl"),
        ], cwd=Path(__file__).resolve().parents[2], stdout=log, stderr=log,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            deadline = time.monotonic() + 25
            while True:
                assert process.poll() is None, "isolated MCP exited during startup"
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    assert time.monotonic() < deadline, "MCP startup timeout"
                    time.sleep(0.1)
            first = configure_codex(tmp_path / "state", port, cli=cli, env=env)
            assert first["ready"], first
            assert first["host_reload_required"]
            second = configure_codex(tmp_path / "state", port, cli=cli, env=env)
            assert second["ready"] and not second["host_reload_required"], second
            assert second["chatgpt_authorization"] == "unverified"
            assert 'model = "custom-preserved-model"' in config.read_text(encoding="utf-8")
        finally:
            # Only this test's child process, never an installed user service.
            process.terminate()
            process.wait(timeout=10)
