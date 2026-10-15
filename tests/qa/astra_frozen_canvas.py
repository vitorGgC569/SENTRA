"""Exercise the frozen broker with isolated state, no GUI or provider inference."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from sentra_canvas.broker import read_endpoint
from scripts.commander.build_windows import _terminate_process_tree


def verify(executable: Path, output: Path):
    executable = executable.resolve(strict=True)
    output.mkdir(parents=True, exist_ok=True)
    proof = json.loads((executable.parent / "build-provenance-canvas.json").read_text())
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    assert proof["executables"][executable.name]["sha256"] == digest
    base = Path(tempfile.mkdtemp(prefix="frozen-canvas-", dir=output))
    workspace, state = base / "workspace", base / "state/canvas"
    workspace.mkdir()
    config = base / "shell-config.json"
    config.write_text("{}", encoding="utf-8")
    env = dict(os.environ, SENTRA_SHELL_CONFIG_FILE=str(config))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(endpoint, path, body=None, auth=True):
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = "Bearer " + endpoint.secret
        try:
            return opener.open(urllib.request.Request(f"http://127.0.0.1:{endpoint.server_port}" + path,
                data=None if body is None else json.dumps(body).encode(), headers=headers), timeout=5)
        except urllib.error.HTTPError as error:
            if not auth:
                raise
            raise RuntimeError(f"Frozen request failed: {path} HTTP {error.code}: " + error.read(1024).decode("utf-8")) from error

    def start():
        process = subprocess.Popen([str(executable), "--root", str(workspace), "--state-dir", str(state), "--broker", "--port", "0"],
            cwd=workspace, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                endpoint = read_endpoint(state)
                if endpoint:
                    return process, endpoint
                if process.poll() is not None:
                    raise RuntimeError("Frozen Canvas exited before readiness: " + str(process.returncode))
                time.sleep(.2)
            raise TimeoutError("Frozen Canvas did not publish an authenticated endpoint")
        except BaseException:
            _terminate_process_tree(process)
            raise

    def stop(process, endpoint):
        try:
            endpoint.request("/api/runtime/shutdown", {"confirm": True})
            process.wait(timeout=20)
            assert process.returncode == 0, process.returncode
        finally:
            _terminate_process_tree(process)

    def stream(endpoint, project_id):
        with request(endpoint, "/api/shell/stream?project_id=" + project_id) as response:
            assert response.headers.get_content_type() == "text/event-stream"
            event = []
            for _ in range(6):
                line = response.readline().decode("utf-8")
                if not line.strip():
                    break
                event.append(line)
            assert any(line.startswith("event: snapshot") for line in event), event
            payload = json.loads(next(line[6:] for line in event if line.startswith("data: ")))
            assert payload["reset"] is True

    started = time.monotonic()
    process, endpoint = start()
    startup_ms = (time.monotonic() - started) * 1000
    first_runtime = endpoint.runtime_id
    try:
        try:
            request(endpoint, "/api/health", auth=False)
        except urllib.error.HTTPError as error:
            assert error.code == 401
        else:
            raise AssertionError("Frozen API accepted unauthenticated request")
        with request(endpoint, "/api/workspaces", {"name": "ASTRA_frozen_QA"}) as response:
            project_id = json.load(response)["id"]
        stream(endpoint, project_id)
        with request(endpoint, "/desktop-assets/manifest.json") as response:
            manifest = json.load(response)
        assert manifest.get("source_inputs"), "Frozen UI lacks source build seal"
        assert any(name.startswith("chunk-") for name in manifest["files"]), "Dynamic chunks lack hashes"
        verified_assets = 0
        for name, expected in manifest["files"].items():
            if Path(name).suffix not in {".js", ".css", ".svg", ".png", ".woff2"}:
                continue
            with request(endpoint, "/desktop-assets/" + name) as response:
                assert hashlib.sha256(response.read()).hexdigest() == expected, name
            verified_assets += 1
    finally:
        stop(process, endpoint)
    process, endpoint = start()
    try:
        assert endpoint.runtime_id != first_runtime
        with request(endpoint, "/api/workspaces") as response:
            projects = json.load(response)
        assert any(item["id"] == project_id for item in projects)
        stream(endpoint, project_id)
    finally:
        stop(process, endpoint)
    report = {"executable": str(executable), "sha256": digest,
              "source_snapshot_sha256": proof.get("source_snapshot_sha256"),
              "isolated_state": str(state), "unauthenticated_api_rejected": True,
              "frozen_broker_restart": True, "workspace_persisted": True,
              "sse_before_and_after_restart": True, "verified_http_assets": verified_assets,
              "single_cold_start_ms": round(startup_ms, 2), "model_inference": False,
              "installed_release_journey": False}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / ".tmp/astra-frozen-qa")
    args = parser.parse_args()
    verify(args.executable, args.output)
