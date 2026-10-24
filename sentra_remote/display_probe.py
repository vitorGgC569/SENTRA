"""Bounded Setup verification of the installed, sandboxed Electron display.

Uses only synthetic loopback content and a new profile. All process descendants
belong to an OS job/session; timeout cannot leave a probe renderer running.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

CHECKS = ("renderer_loaded", "node_isolated", "context_isolated", "sandbox",
          "web_security", "ephemeral_session", "popup_blocked", "network_fenced")


def _verified_record(directory: Path, nonce: str, code: int, ticket: Path,
                     primary_requests: int, foreign_requests: int) -> bool:
    if code != 0 or ticket.exists() or ticket.is_symlink() or primary_requests < 1 or foreign_requests != 0:
        return False
    path = directory / "result.json"
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2048:
            return False
        result = json.loads(path.read_text(encoding="utf-8"))
        return (isinstance(result, dict) and set(result) == {"schema", "nonce", *CHECKS}
                and type(result["schema"]) is int and result["schema"] == 1
                and result["nonce"] == nonce and all(result[key] is True for key in CHECKS))
    except (OSError, ValueError, TypeError):
        return False


def probe_installed_display(install_dir: Path, *, timeout_s: float = 25) -> dict:
    """Return fixed, credential-free evidence; dependency hashes precede execution."""
    from scripts.commander.stage_electron import validate_electron_payload
    root = Path(install_dir).resolve() / "sentra-electron"
    try:
        validate_electron_payload(root)
    except (OSError, ValueError):
        return {"ok": False, "reason": "display_payload_invalid"}
    electron=_run_display_probe(root, timeout_s=timeout_s)
    if electron.get('ok') is True:return {**electron,'backend':'electron'}
    native=_run_native_display_probe(Path(install_dir),timeout_s=timeout_s)
    return {**native,'electron':electron,'external_bar_available':False}


def _run_native_display_probe(install_dir: Path, *, timeout_s: float) -> dict:
    from sentra_canvas.owned_process import TaskProcess
    directory=Path(tempfile.mkdtemp(prefix='sentra-native-probe-'))
    report=directory/'result.json';nonce=secrets.token_hex(16);task=None
    try:
        executable=Path(install_dir).resolve()/'sentra-canvas.exe'
        if not executable.is_file():return {'ok':False,'reason':'native_display_unavailable','backend':'native'}
        task=TaskProcess([str(executable),'--native-display-check',str(report),nonce],
            cwd=install_dir,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            env={**os.environ,'PYINSTALLER_RESET_ENVIRONMENT':'1'},creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        task.communicate(timeout=max(10,min(45,float(timeout_s))))
        value=json.loads(report.read_text()) if report.is_file() and report.stat().st_size<2048 else {}
        fields=('renderer_loaded','node_absent','network_blocked','window_destroyed','frozen')
        verified=(task.returncode==0 and value.get('schema')==1 and value.get('nonce')==nonce
                  and value.get('backend')=='native' and all(value.get(key) is True for key in fields))
        return {'ok':verified,'reason':'native_display_verified' if verified else 'native_display_unconfirmed',
                'backend':'native',**({key:True for key in fields} if verified else {})}
    except Exception:
        return {'ok':False,'reason':'native_display_unavailable','backend':'native'}
    finally:
        if task is not None:
            task.terminate_tree()
            try:task.communicate(timeout=3)
            except (OSError,subprocess.TimeoutExpired):pass
        # Only files created under our freshly allocated directory are removed.
        report.unlink(missing_ok=True)
        if not directory.is_symlink() and not directory.is_junction():directory.rmdir()


def _run_display_probe(root: Path, *, timeout_s: float) -> dict:
    from sentra_canvas.owned_process import TaskProcess
    if os.name != "nt":
        return {"ok": False, "reason": "display_platform_unsupported"}
    timeout_s = max(1, min(30, float(timeout_s)))
    nonce = secrets.token_hex(16)
    temp_root = Path(tempfile.gettempdir()).resolve()
    directory = Path(tempfile.mkdtemp(prefix="sentra-display-probe-", dir=temp_root))
    ticket_id = secrets.token_hex(16)
    ticket = temp_root / ("sentra-electron-" + ticket_id + ".json")
    requests = [0, 0]
    servers, threads = [], []
    task = None
    try:
        for index in range(2):
            def handler_for(index):
                class Handler(BaseHTTPRequestHandler):
                    def do_GET(self):
                        requests[index] += 1
                        if index == 0 and urlsplit(self.path).path != "/desktop.html":
                            self.send_error(404)
                            return
                        raw = ('<!doctype html><meta name="sentra-display-probe" content="'
                               + nonce + '"><title>SENTRA Setup display check</title>').encode()
                        self.send_response(200)
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.send_header("Content-Length", str(len(raw)))
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.end_headers()
                        self.wfile.write(raw)
                    def log_message(self, *_args):
                        pass
                return Handler
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(index))
            server.daemon_threads = True
            thread = threading.Thread(target=lambda s=server: s.serve_forever(poll_interval=0.05), daemon=True)
            servers.append(server)
            threads.append(thread)
            thread.start()
        payload = {"schema": 1, "port": servers[0].server_port,
                   "secret": secrets.token_urlsafe(32), "expires_at": int((time.time() + 29) * 1000),
                   "probe_nonce": nonce, "probe_directory": str(directory),
                   "probe_foreign_port": servers[1].server_port}
        with ticket.open("x", encoding="utf-8") as stream:
            os.chmod(ticket, 0o600)
            json.dump(payload, stream, separators=(",", ":"))
        environment = dict(os.environ)
        for name in ("ELECTRON_RUN_AS_NODE", "ELECTRON_OVERRIDE_DIST_PATH", "NODE_OPTIONS", "NODE_PATH"):
            environment.pop(name, None)
        task = TaskProcess([str(root / "electron.exe"), str(root / "healthcheck.cjs"),
                            "--user-data-dir=" + str(directory / "profile"), "--sentra-ticket=" + ticket_id],
                           cwd=root, env=environment, stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            task.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return {"ok": False, "reason": "display_probe_timeout", "process_started": True, "exit_code": None}
        if not _verified_record(directory, nonce, task.returncode, ticket, *requests):
            return {"ok": False, "reason": "display_probe_failed", "process_started": True, "exit_code": task.returncode}
        return {"ok": True, "reason": "display_probe_verified", "process_started": True, "exit_code": 0,
                **{key: True for key in CHECKS}}
    except Exception:
        # Exception text may include an environment/profile path or command line.
        return {"ok": False, "reason": "display_probe_failed", "process_started": task is not None, "exit_code": None}
    finally:
        if task is not None:
            try:
                task.terminate_tree()
                task.communicate(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                pass
        for index, server in enumerate(servers):
            if index < len(threads) and threads[index].is_alive():
                server.shutdown()
            server.server_close()
        for thread in threads:
            if thread.ident is not None:
                thread.join(timeout=1)
        ticket.unlink(missing_ok=True)
        # Never recursively delete a redirected path or a different temp tree.
        if (directory.parent.resolve() == temp_root and directory.name.startswith("sentra-display-probe-")
                and not directory.is_symlink() and not directory.is_junction()
                and directory.resolve().parent == temp_root):
            try:
                shutil.rmtree(directory)
            except OSError:
                pass
