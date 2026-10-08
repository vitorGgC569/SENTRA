import io
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from sentra_cli.client import ModelClient
from sentra_cli.config import CLIConfig


def test_turn_authority_token_uses_product_state(tmp_path: Path):
    token_dir = tmp_path / "web-models"
    token_dir.mkdir(parents=True)
    expected = "t" * 64
    (token_dir / "turn-authority.token").write_text(expected + "\n", encoding="utf-8")
    fake_paths = MagicMock(state_dir=tmp_path)
    with patch.dict("os.environ", {"SENTRA_TURN_AUTHORITY_TOKEN": ""}, clear=False), patch(
        "sentra_remote.product.ProductPaths.default", return_value=fake_paths
    ):
        assert ModelClient._turn_authority_token() == expected


def test_spawn_browser_host_injects_sentra_authority(tmp_path: Path):
    cfg = CLIConfig(workspace=tmp_path)
    client = ModelClient(cfg)
    executable = tmp_path / "Codex Web GPT.exe"
    executable.write_bytes(b"test")
    process = MagicMock(pid=4321)
    process.poll.return_value = None
    with patch.object(client, "_browser_host_ready", side_effect=[False, True]), patch.object(
        client, "_browser_host_executable_path", return_value=executable
    ), patch.object(
        client, "_browser_relay_token_file", return_value=None
    ), patch.object(
        client, "_turn_authority_token", return_value="a" * 64
    ), patch("sentra_cli.client.subprocess.Popen", return_value=process) as popen:
        result = client._spawn_browser_host()
    assert result == "browser-host pid=4321"
    env = popen.call_args.kwargs["env"]
    assert env["SENTRA_BROWSER_HOST_ONLY"] == "1"
    assert env["SENTRA_MANAGED_TUNNEL"] == "1"
    assert env["SENTRA_TURN_AUTHORITY_TOKEN"] == "a" * 64
    assert env["SENTRA_WEB_GATEWAY_URL"] == cfg.gateway_url

def test_pid_running_recognizes_current_process():
    import os
    assert ModelClient._pid_running(os.getpid()) is True

def test_wait_browser_host_turn_ready_waits_through_session_refresh(tmp_path: Path):
    cfg = CLIConfig(workspace=tmp_path, gateway_start_timeout_s=5.0)
    client = ModelClient(cfg)
    descriptor = tmp_path / "launcher-browser.json"
    descriptor.write_text(
        '{"control":{"endpoint":"http://127.0.0.1:62080",'
        '"token":"' + ('x' * 48) + '"}}',
        encoding="utf-8",
    )
    busy = urllib.error.HTTPError(
        "http://127.0.0.1:62080/v1/session/inspect",
        400,
        "bad request",
        {},
        io.BytesIO(
            b'{"error":"ChatGPT browser is busy with session refresh"}'
        ),
    )
    response = MagicMock()
    response.status = 200
    response.read.return_value = (
        b'{"authenticated":true,"temporary":true,"url":"https://chatgpt.com/"}'
    )
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    with patch.object(
        client, "_browser_descriptor_path", return_value=descriptor
    ), patch(
        "sentra_cli.client.urllib.request.urlopen",
        side_effect=[busy, response],
    ), patch("sentra_cli.client.time.sleep", return_value=None):
        ready, detail = client._wait_browser_host_turn_ready(timeout_s=1.0)
    assert ready is True
    assert detail == "ready"
