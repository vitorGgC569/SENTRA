from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sentra_remote import local_runtime as local_runtime_mod
from sentra_remote import product as product_mod
from sentra_remote.local_runtime import LocalRuntime
from sentra_remote.product import ProductPaths, ProductSettings


def _runtime(tmp_path: Path) -> LocalRuntime:
    install = tmp_path / "install"
    state = tmp_path / "state"
    install.mkdir()
    (install / "edge_extension").mkdir()
    token = state / "browser" / "relay-token"
    token.parent.mkdir(parents=True)
    token.write_text("x" * 48, encoding="utf-8")
    return LocalRuntime(ProductPaths(install, state), ProductSettings())


def test_runtime_authority_registry_overrides_source_state_heuristic(tmp_path: Path, monkeypatch) -> None:
    local = tmp_path / "local"
    install = tmp_path / "install"
    chosen = tmp_path / "chosen-state"
    install.mkdir()
    chosen.mkdir()
    source_tunnel = install / ".sentra" / "tunnel"
    source_tunnel.mkdir(parents=True)
    (source_tunnel / "runtime-key.dpapi").write_text("legacy", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.delenv("SENTRA_STATE_DIR", raising=False)

    ProductPaths(install.resolve(), chosen.resolve()).persist_runtime_authority()
    resolved = ProductPaths.default(install)

    assert resolved.state_dir == chosen.resolve()


def test_source_checkout_is_canonical_configured_workspace(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    (runtime.paths.install_dir / ".git").mkdir()
    (runtime.paths.install_dir / "sentra_mcp").mkdir()

    roots = runtime._roots()

    assert roots == [str(runtime.paths.install_dir.resolve())]


def test_installed_runtime_keeps_product_state_out_of_workspace_roots(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)

    roots = runtime._roots()

    expected = (runtime.paths.state_dir / "default-workspace").resolve()
    assert roots == [str(expected)]
    assert expected.is_dir()


def test_existing_relay_requires_authenticated_pairing(tmp_path: Path, monkeypatch) -> None:
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(local_runtime_mod, "tcp_open", lambda *_args: True)

    def fake_json_get(url: str, **_kwargs):
        if url.endswith("/health"):
            return {"ok": True}
        if url.endswith("/auth/check"):
            raise PermissionError("401")
        raise AssertionError(url)

    monkeypatch.setattr(local_runtime_mod, "json_get", fake_json_get)
    result = runtime.start_relay()
    assert result["ok"] is False
    assert result["reason"] == "relay_auth_mismatch"


def test_existing_relay_is_reused_only_after_auth_check(tmp_path: Path, monkeypatch) -> None:
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(local_runtime_mod, "tcp_open", lambda *_args: True)
    seen: list[str] = []

    def fake_json_get(url: str, **_kwargs):
        seen.append(url)
        if url.endswith("/health"):
            return {"ok": True}
        if url.endswith("/auth/check"):
            return {"ok": True}
        raise AssertionError(url)

    monkeypatch.setattr(local_runtime_mod, "json_get", fake_json_get)
    monkeypatch.setattr(runtime, "_persisted_pid", lambda _name: 4242)
    result = runtime.start_relay()
    assert result == {"ok": True, "already_running": True, "pid": 4242}
    assert seen[-1].endswith("/auth/check")


def test_product_status_requires_authenticated_relay(tmp_path: Path, monkeypatch) -> None:
    runtime = _runtime(tmp_path)
    paths = runtime.paths
    settings = runtime.settings

    monkeypatch.setattr(
        product_mod,
        "tcp_open",
        lambda _host, port: port == settings.relay_port,
    )
    monkeypatch.setattr(product_mod, "ensure_instance_id", lambda _paths: "instance")
    monkeypatch.setattr(product_mod, "load_tunnel_config", lambda _paths: {})
    monkeypatch.setattr(product_mod, "_docker_status", lambda: {"ok": False})
    monkeypatch.setattr(product_mod, "_git_status", lambda: {"ok": True})

    def fake_json_get(url: str, **_kwargs):
        if url.endswith("/health"):
            return {"ok": True, "workers_online": ["TAB-1"]}
        if url.endswith("/auth/check"):
            raise PermissionError("401")
        raise AssertionError(url)

    monkeypatch.setattr(product_mod, "json_get", fake_json_get)
    report = product_mod.collect_product_status(paths, settings)
    assert report["relay"]["ok"] is False
    assert report["relay"]["authenticated"] is False
    assert report["edge"]["ok"] is False
    assert report["relay"]["workers_online"] == ["TAB-1"]


def test_product_status_accepts_idle_extension_heartbeat_without_workers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime = _runtime(tmp_path)
    paths = runtime.paths
    settings = runtime.settings

    monkeypatch.setattr(
        product_mod,
        "tcp_open",
        lambda _host, port: port == settings.relay_port,
    )
    monkeypatch.setattr(product_mod, "ensure_instance_id", lambda _paths: "instance")
    monkeypatch.setattr(product_mod, "load_tunnel_config", lambda _paths: {})
    monkeypatch.setattr(product_mod, "_docker_status", lambda: {"ok": False})
    monkeypatch.setattr(product_mod, "_git_status", lambda: {"ok": True})

    def fake_json_get(url: str, **_kwargs):
        if url.endswith("/health"):
            return {
                "ok": True,
                "workers_online": [],
                "extension": {
                    "online": True,
                    "last_seen": 123.0,
                    "status": {"sw_version": "1.6.50"},
                },
            }
        if url.endswith("/auth/check"):
            return {"ok": True}
        raise AssertionError(url)

    monkeypatch.setattr(product_mod, "json_get", fake_json_get)
    report = product_mod.collect_product_status(paths, settings)

    assert report["relay"]["ok"] is True
    assert report["relay"]["workers_online"] == []
    assert report["edge"]["ok"] is True
    assert report["edge"]["extension_online"] is True
    assert report["edge"]["workers"] == []


def test_product_status_marks_invalidated_runtime_key_as_reauth_required(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime = _runtime(tmp_path)
    paths = runtime.paths
    settings = runtime.settings

    paths.tunnel_dir.mkdir(parents=True, exist_ok=True)
    (paths.tunnel_dir / "health-url.txt").write_text(
        "http://127.0.0.1:45678\n",
        encoding="utf-8",
    )
    logs = paths.state_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "tunnel.err.log").write_text(
        "controlplane status=401 error_code=token_invalidated\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(product_mod, "tcp_open", lambda *_args: False)
    monkeypatch.setattr(
        product_mod,
        "load_tunnel_config",
        lambda _paths: {"tunnel_id": "tunnel-test"},
    )
    monkeypatch.setattr(product_mod, "_docker_status", lambda: {"ok": False})
    monkeypatch.setattr(product_mod, "_git_status", lambda: {"ok": True})

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(url, **_kwargs):
        if str(url).endswith("/healthz"):
            return _Response()
        if str(url).endswith("/readyz"):
            raise OSError("readiness probe failed")
        raise AssertionError(url)

    monkeypatch.setattr(product_mod.urllib.request, "urlopen", fake_urlopen)

    report = product_mod.collect_product_status(paths, settings)

    assert report["tunnel"]["ok"] is False
    assert report["tunnel"]["reauth_required"] is True
    assert report["tunnel"]["control_plane"] == "REAUTH_REQUIRED"
    assert "invalidated" in report["tunnel"]["detail"].lower()


def test_matching_install_pids_requires_exact_binary(tmp_path: Path, monkeypatch) -> None:
    runtime = _runtime(tmp_path)
    tunnel_client = runtime.paths.tunnel_client
    tunnel_client.write_bytes(b"MZ")
    foreign = tmp_path / "foreign" / "tunnel-client.exe"
    foreign.parent.mkdir()
    foreign.write_bytes(b"MZ")

    monkeypatch.setattr(local_runtime_mod.os, "name", "nt")
    monkeypatch.setattr(
        local_runtime_mod.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout='"tunnel-client.exe","111","Console","1","1 K"\n'
                   '"tunnel-client.exe","222","Console","1","1 K"\n',
        ),
    )
    monkeypatch.setattr(
        runtime,
        "_windows_process_path",
        lambda pid: tunnel_client.resolve() if pid == 111 else foreign.resolve(),
    )

    assert runtime._matching_install_pids("tunnel") == [111]


def test_tunnel_supervisor_is_fail_closed_for_reauth_and_recovers_transient_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime = _runtime(tmp_path)
    runtime.settings.autostart_tunnel = True

    healthy = {
        "mcp": {"ok": True},
        "tunnel": {"ok": True, "configured": True},
    }
    assert runtime.supervise_once(healthy, now=100.0)["state"] == "HEALTHY"

    calls: list[str] = []
    monkeypatch.setattr(runtime, "stop", lambda name: calls.append(f"stop:{name}") or True)
    monkeypatch.setattr(
        runtime,
        "start_tunnel",
        lambda: calls.append("start:tunnel") or {"ok": True, "pid": 1234},
    )
    monkeypatch.setattr(local_runtime_mod.time, "sleep", lambda _seconds: None)

    reauth = {
        "mcp": {"ok": True},
        "tunnel": {
            "ok": False,
            "configured": True,
            "reauth_required": True,
        },
    }
    state = runtime.supervise_once(reauth, now=110.0)
    assert state["state"] == "REAUTH_REQUIRED"
    assert calls == []

    degraded = {
        "mcp": {"ok": True},
        "tunnel": {"ok": False, "configured": True},
    }
    first = runtime.supervise_once(degraded, now=120.0)
    assert first["state"] == "DEGRADED"
    assert calls == []

    recovered = runtime.supervise_once(
        degraded,
        now=120.0 + runtime.TUNNEL_FAILURE_GRACE_S + 0.1,
    )
    assert recovered["state"] == "RECOVERING"
    assert recovered["action"] == "restart_tunnel"
    assert calls == ["stop:tunnel", "start:tunnel"]

    backoff = runtime.supervise_once(
        degraded,
        now=120.0 + runtime.TUNNEL_FAILURE_GRACE_S + 0.2,
    )
    assert backoff["state"] in {"DEGRADED", "BACKOFF"}
    assert calls == ["stop:tunnel", "start:tunnel"]


def test_start_tunnel_requires_authoritative_mcp_before_new_spawn(tmp_path: Path, monkeypatch) -> None:
    runtime = _runtime(tmp_path)
    runtime.paths.tunnel_client.write_bytes(b"MZ")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(
        local_runtime_mod,
        "load_tunnel_config",
        lambda *_args, **_kwargs: {
            "tunnel_id": "tunnel_test_requires_mcp",
            "runtime_key": "x" * 32,
        },
    )
    monkeypatch.setattr(runtime, "_persisted_pid", lambda _name: None)
    monkeypatch.setattr(runtime, "_matching_install_pids", lambda _name: [])
    monkeypatch.setattr(runtime, "_mcp_health", lambda: None)

    result = runtime.start_tunnel()

    assert result["ok"] is False
    assert result["reason"] == "mcp_not_ready"


def test_start_tunnel_adopts_single_orphaned_instance(tmp_path: Path, monkeypatch) -> None:
    runtime = _runtime(tmp_path)
    runtime.paths.tunnel_client.write_bytes(b"MZ")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(
        local_runtime_mod,
        "load_tunnel_config",
        lambda *_args, **_kwargs: {
            "tunnel_id": "tunnel_test_1234567890",
            "runtime_key": "x" * 32,
        },
    )
    monkeypatch.setattr(runtime, "_persisted_pid", lambda _name: None)
    monkeypatch.setattr(runtime, "_matching_install_pids", lambda _name: [4242])

    result = runtime.start_tunnel()

    assert result == {
        "ok": True,
        "already_running": True,
        "adopted": True,
        "pid": 4242,
    }
    assert (runtime.runtime_dir / "tunnel.pid").read_text(encoding="ascii") == "4242"


def test_start_tunnel_fails_closed_on_duplicate_instances(tmp_path: Path, monkeypatch) -> None:
    runtime = _runtime(tmp_path)
    runtime.paths.tunnel_client.write_bytes(b"MZ")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(
        local_runtime_mod,
        "load_tunnel_config",
        lambda *_args, **_kwargs: {
            "tunnel_id": "tunnel_test_1234567890",
            "runtime_key": "x" * 32,
        },
    )
    monkeypatch.setattr(runtime, "_persisted_pid", lambda _name: None)
    monkeypatch.setattr(runtime, "_matching_install_pids", lambda _name: [111, 222])

    result = runtime.start_tunnel()

    assert result == {
        "ok": False,
        "reason": "duplicate_tunnel_processes",
        "pids": [111, 222],
    }


def test_stop_terminates_all_verified_duplicate_instances(tmp_path: Path, monkeypatch) -> None:
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(local_runtime_mod.os, "name", "nt")
    monkeypatch.setattr(runtime, "_persisted_pid", lambda _name: None)
    monkeypatch.setattr(runtime, "_matching_install_pids", lambda _name: [111, 222])
    calls: list[list[str]] = []

    def fake_run(args, **_kwargs):
        calls.append(list(args))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(local_runtime_mod.subprocess, "run", fake_run)

    assert runtime.stop("tunnel") is True
    assert [call[:4] for call in calls] == [
        ["taskkill", "/PID", "111", "/T"],
        ["taskkill", "/PID", "222", "/T"],
    ]
    assert all(call[-1] == "/F" for call in calls)


def test_start_tunnel_adopts_global_worker_from_other_state_root(tmp_path: Path, monkeypatch) -> None:
    from sentra_remote.tunnel_singleton import TunnelSingleton

    runtime = _runtime(tmp_path)
    runtime.paths.tunnel_client.write_bytes(b"MZ")
    other_executable = tmp_path / "other" / "tunnel-client.exe"
    other_executable.parent.mkdir()
    other_executable.write_bytes(b"MZ")
    tunnel_id = "tunnel_global_adopt_12345"

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(
        local_runtime_mod,
        "load_tunnel_config",
        lambda *_args, **_kwargs: {"tunnel_id": tunnel_id, "runtime_key": "x" * 32},
    )
    monkeypatch.setattr(
        runtime,
        "_windows_process_path",
        lambda pid: other_executable.resolve() if pid == 777 else None,
    )
    singleton = TunnelSingleton(
        tunnel_id,
        tmp_path / "other-state",
        process_path=runtime._windows_process_path,
    )
    singleton.write(777, other_executable, tmp_path / "other-state")
    monkeypatch.setattr(
        runtime,
        "_persisted_pid",
        lambda _name: (_ for _ in ()).throw(AssertionError("global registry must win")),
    )

    result = runtime.start_tunnel()

    assert result["ok"] is True
    assert result["adopted_global"] is True
    assert result["pid"] == 777
    assert (runtime.runtime_dir / "tunnel.pid").read_text(encoding="ascii") == "777"


def test_stop_tunnel_terminates_registered_global_worker(tmp_path: Path, monkeypatch) -> None:
    from sentra_remote.tunnel_singleton import TunnelSingleton

    runtime = _runtime(tmp_path)
    runtime.paths.tunnel_client.write_bytes(b"MZ")
    other_executable = tmp_path / "other" / "tunnel-client.exe"
    other_executable.parent.mkdir()
    other_executable.write_bytes(b"MZ")
    tunnel_id = "tunnel_global_stop_12345"

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(local_runtime_mod.os, "name", "nt")
    monkeypatch.setattr(
        local_runtime_mod,
        "load_tunnel_config",
        lambda *_args, **_kwargs: {"tunnel_id": tunnel_id},
    )
    monkeypatch.setattr(
        runtime,
        "_windows_process_path",
        lambda pid: other_executable.resolve() if pid == 888 else None,
    )
    monkeypatch.setattr(runtime, "_persisted_pid", lambda _name: None)
    monkeypatch.setattr(runtime, "_matching_install_pids", lambda _name: [])

    singleton = TunnelSingleton(
        tunnel_id,
        tmp_path / "other-state",
        process_path=runtime._windows_process_path,
    )
    singleton.write(888, other_executable, tmp_path / "other-state")

    calls = []
    monkeypatch.setattr(
        local_runtime_mod.subprocess,
        "run",
        lambda args, **kwargs: calls.append(list(args)) or SimpleNamespace(returncode=0),
    )

    assert runtime.stop("tunnel") is True
    assert calls == [["taskkill", "/PID", "888", "/T", "/F"]]
    assert not singleton.registry_path.exists()
