"""One owner-initiated account setup per installation, with observable progress."""
from __future__ import annotations

import threading

_lock = threading.Lock()
_jobs = {}


def setup_status(paths):
    with _lock:
        return dict(_jobs.get(str(paths.state_dir.resolve()), {"running": False, "state": "not_started", "detail": ""}))


def start_account_setup(paths):
    key = str(paths.state_dir.resolve())
    with _lock:
        previous = _jobs.get(key)
        if previous and previous.get("running"):
            return dict(previous)
        record = {"running": True, "state": "configuring", "detail": "Preparando o navegador integrado…",
                  "verification_prompt": ""}
        _jobs[key] = record

    def notify(event, message):
        with _lock:
            if event == "verification_prompt":
                record["verification_prompt"] = message
            elif event in {"progress", "browser_session", "workspace_required", "tunnel_ready"}:
                record["detail"] = str(message)[:1200]

    def worker():
        try:
            from .openai_auto_setup import run_setup_enrollment
            result = run_setup_enrollment(paths, notify, browser="sentra")
            ok = result.get("ok") is True and result.get("mcp_roundtrip_verified") is True
            with _lock:
                record.update(running=False, state="verified" if ok else "needs_attention",
                              reason=str(result.get("reason", "account_setup_incomplete"))[:100],
                              detail="Conexão verificada por uma chamada MCP desta configuração." if ok else
                              "A configuração precisa de atenção. Conclua login/autorização no navegador ou tente novamente para retomar; as credenciais salvas são preservadas.")
                record["verification_prompt"] = ""
        except Exception:
            with _lock:
                record.update(running=False, state="needs_attention", reason="account_setup_failed",
                              detail="Não foi possível concluir. Verifique os componentes instalados e tente novamente.")

    threading.Thread(target=worker, name="sentra-account-setup", daemon=True).start()
    return setup_status(paths)
