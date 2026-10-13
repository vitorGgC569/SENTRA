"""Internal diagnostics and safe, separately consented support export for SENTRA.

Internal operational reports are *never* sent automatically. Shared reports use
an allowlist, not regex-only blacklisting: arbitrary error strings and remote
service payloads cannot leak identifying material.
"""
from __future__ import annotations

import json
import platform
import sys
import urllib.request
from pathlib import Path
from typing import Any

from .agent_config import AgentConfig


def collect(config_path: Path) -> dict[str, Any]:
    """Internal-only details, permitted for an authenticated local operator."""
    result: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "hostname": platform.node(),
        "config_exists": config_path.is_file(),
    }
    if not config_path.is_file():
        return result
    try:
        config = AgentConfig.load(config_path)
    except Exception as exc:
        result["config_error"] = str(exc)[:300]
        return result
    result["device"] = {
        "device_id": config.device_id,
        "name": config.name,
        "relay_url": config.relay_url,
        "allowed_roots": list(config.allowed_roots),
        "audit_log": config.audit_log,
        "process_mode": config.process_mode,
        "profile": config.profile,
        "access_scope": config.access_scope,
        "tool_surfaces": list(config.tool_surfaces),
        "token_present": bool(config.device_token),
    }
    try:
        with urllib.request.urlopen(config.relay_url.rstrip("/") + "/health", timeout=3) as response:
            result["relay"] = json.loads(response.read(65536))
    except Exception as exc:
        result["relay"] = {"ok": False, "error": str(exc)[:300]}
    audit = Path(config.audit_log)
    result["audit_exists"] = audit.is_file()
    result["audit_size"] = audit.stat().st_size if audit.is_file() else 0
    return result


def shareable_report(raw: dict[str, Any]) -> dict[str, Any]:
    """Strict bounded projection for a report someone can safely review.

    Excludes identifiers, user paths, hostnames, URLs, chat/task content,
    arbitrary exception messages and upstream health payloads. Caller reviews
    the resulting JSON before sharing; even the report itself stays local.
    """
    device = raw.get("device") if isinstance(raw.get("device"), dict) else {}
    public: dict[str, Any] = {
        "schema_version": 1,
        "kind": "sentra_shareable_diagnostics",
        "config_present": raw.get("config_exists") is True,
        "config_parse_ok": bool(raw.get("config_exists") and "config_error" not in raw),
        "python_major_minor": "",
        "platform_family": "unknown",
        "device": {
            "token_configured": device.get("token_present") is True,
            "audit_present": raw.get("audit_exists") is True,
        },
        "relay": {"healthy": False, "reachable": False},
    }
    python = raw.get("python")
    if isinstance(python, str):
        parts = python.split(".")
        if len(parts) >= 2 and all(part.isdigit() and len(part) <= 3 for part in parts[:2]):
            public["python_major_minor"] = ".".join(parts[:2])
    platform_str = raw.get("platform")
    if isinstance(platform_str, str):
        family = platform_str.split("-", 1)[0].casefold()
        if family.startswith("windows"):
            public["platform_family"] = "windows"
        elif family.startswith("linux"):
            public["platform_family"] = "linux"
        elif family.startswith("darwin") or family.startswith("macos"):
            public["platform_family"] = "macos"
    for name, allowed in (
        ("process_mode", {"disabled", "read_only", "sandbox", "restricted", "native", "docker", "host", "isolated"}),
        ("profile", {"safe", "full", "balanced", "developer"}),
        ("access_scope", {"workspace", "all", "selected", "read_only", "none"}),
    ):
        value = device.get(name)
        if isinstance(value, str) and value.casefold() in allowed:
            public["device"][name] = value.casefold()
    surfaces = device.get("tool_surfaces")
    if isinstance(surfaces, list):
        public["device"]["surface_count"] = min(len(surfaces), 1000)
    roots = device.get("allowed_roots")
    if isinstance(roots, list):
        public["device"]["workspace_count"] = min(len(roots), 1000)
    relay = raw.get("relay")
    if isinstance(relay, dict):
        public["relay"]["reachable"] = "error" not in relay
        public["relay"]["healthy"] = relay.get("ok") is True
    shell = raw.get("shell")
    if isinstance(shell, dict):
        # Allowlisted projection only: readiness + missing bundle labels.
        status = shell.get("status")
        if status in {"shell_ready", "shell_pending", "unchecked"}:
            public["shell"] = {"status": status}
            missing = shell.get("missing")
            if isinstance(missing, list):
                public["shell"]["missing_count"] = min(len(missing), 64)
    install = raw.get("installation")
    if isinstance(install, dict):
        phase = install.get("doctor_phase")
        if phase in {"files_present", "repair_needed", "unowned", "invalid_manifest"}:
            public["installation"] = {"doctor_phase": phase}
    setup = raw.get("setup_states")
    if isinstance(setup, dict):
        # Allowlisted axes only: each axis collapses to a closed vocabulary.
        axes: dict[str, Any] = {}
        local = setup.get("local") if isinstance(setup.get("local"), dict) else {}
        axes["local_ready"] = local.get("ready") is True
        tunnel = setup.get("tunnel") if isinstance(setup.get("tunnel"), dict) else {}
        axes["tunnel_online"] = tunnel.get("online") is True
        account = setup.get("account_app") if isinstance(setup.get("account_app"), dict) else {}
        if account.get("state") in {"observed", "tool-observed-unverified", "unobserved"}:
            axes["account_app"] = account["state"]
        tools = setup.get("tools") if isinstance(setup.get("tools"), dict) else {}
        if tools.get("state") in {"authorized", "pending", "unverified"}:
            axes["tools"] = tools["state"]
        version = setup.get("version") if isinstance(setup.get("version"), dict) else {}
        if version.get("state") in {"current", "stale", "unknown"}:
            axes["version"] = version["state"]
        extension = setup.get("extension") if isinstance(setup.get("extension"), dict) else {}
        if extension.get("state") in {"absent", "installed", "paired", "login", "revoked"}:
            axes["extension"] = extension["state"]
        public["setup"] = axes
    providers = raw.get("providers")
    if isinstance(providers, dict):
        states = providers.get("providers") if isinstance(providers.get("providers"), dict) else providers
        if isinstance(states, dict):
            counts: dict[str, int] = {}
            for entry in states.values():
                state = entry.get("state") if isinstance(entry, dict) else None
                if state in {"absent", "installable", "installing", "ready",
                             "degraded", "unavailable", "removed"}:
                    counts[state] = min(counts.get(state, 0) + 1, 64)
            public["providers"] = {"states": counts, "total": min(len(states), 64)}
    return public


_IP_RE = None
_URL_RE = None
_EMAIL_RE = None
_PATH_RE = None


def _redaction_patterns():
    import re
    global _IP_RE, _URL_RE, _EMAIL_RE, _PATH_RE
    if _IP_RE is None:
        _IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b|\b(?:[0-9a-fA-F]{0,4}:){2,}[0-9a-fA-F:.]+\b")
        _URL_RE = re.compile(r"https?://[^\s\"'<>]+|wss?://[^\s\"'<>]+", re.IGNORECASE)
        _EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
        _PATH_RE = re.compile(r"[A-Za-z]:\\[^\s\"'<>]*|/(?:home|Users|tmp|var|etc)/[^\s\"'<>]*")
    return _IP_RE, _URL_RE, _EMAIL_RE, _PATH_RE


def redact_text_preview(text: str, *, titles: list[str] | None = None,
                        projects: list[str] | None = None) -> dict[str, object]:
    """Redact a free-text diagnostics field for the share preview.

    Redacts IP/URL/path/email plus caller-supplied title/project strings
    (matched literally, longest first). Returns the redacted text and per
    class counts so the operator can review what was removed. Bounded to
    64 KiB of input; larger inputs are refused rather than truncated.
    """
    if not isinstance(text, str):
        raise ValueError("diagnostics preview text must be a string")
    if len(text.encode("utf-8", errors="replace")) > 65536:
        raise ValueError("diagnostics preview text exceeds 64 KiB")
    ip_re, url_re, email_re, path_re = _redaction_patterns()
    counts = {"ip": 0, "url": 0, "path": 0, "email": 0, "title": 0, "project": 0}

    def _sub(pattern, value: str, label: str, token: str) -> str:
        found = pattern.findall(value)
        counts[label] += len(found)
        return pattern.sub(token, value)

    redacted = _sub(ip_re, text, "ip", "[redacted-ip]")
    redacted = _sub(url_re, redacted, "url", "[redacted-url]")
    redacted = _sub(email_re, redacted, "email", "[redacted-email]")
    redacted = _sub(path_re, redacted, "path", "[redacted-path]")
    for label, words, token in (("title", titles or [], "[redacted-title]"),
                                ("project", projects or [], "[redacted-project]")):
        for word in sorted({w for w in words if isinstance(w, str) and w.strip()}, key=len, reverse=True):
            if word in redacted:
                counts[label] += redacted.count(word)
                redacted = redacted.replace(word, token)
    return {"schema": 1, "redacted": redacted, "counts": counts}


def preview_export(raw: dict[str, Any], free_text: dict[str, str] | None = None, *,
                   titles: list[str] | None = None,
                   projects: list[str] | None = None) -> dict[str, Any]:
    """Shareable report plus a redacted preview of operator-supplied notes.

    The allowlisted shareable_report stays the only machine-derived shared
    content; free-text notes are preview-only and redacted before review.
    Nothing is sent anywhere by this function.
    """
    base = shareable_report(raw if isinstance(raw, dict) else {})
    previews: dict[str, Any] = {}
    for field, value in (free_text or {}).items():
        if not isinstance(field, str) or not isinstance(value, str):
            continue
        if len(field) > 64:
            continue
        previews[field] = redact_text_preview(value, titles=titles, projects=projects)
    return {"schema": 1, "shareable": base, "preview": previews,
            "note": "review locally before sharing; nothing was transmitted"}


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="sentra-diagnostics")
    parser.add_argument("--config", default=str(Path.home() / ".sentra" / "agent.json"))
    parser.add_argument("--output", help="Write to a local file; review it before sharing")
    parser.add_argument("--internal", action="store_true",
                        help="Include private machine metadata (local troubleshooting ONLY)")
    parser.add_argument("--preview-note", default="",
                        help="Operator note to redact-preview (max 8 KiB); never transmitted")
    parser.add_argument("--preview-title", action="append", default=[],
                        help="Title string to redact from the preview (repeatable)")
    parser.add_argument("--preview-project", action="append", default=[],
                        help="Project string to redact from the preview (repeatable)")
    args = parser.parse_args(argv)
    raw = collect(Path(args.config).expanduser())
    if args.preview_note and args.internal:
        parser.error("--preview-note cannot be combined with --internal")
    if args.preview_note:
        if len(args.preview_note.encode("utf-8")) > 8192:
            parser.error("--preview-note exceeds 8 KiB")
        data = preview_export(raw, {"note": args.preview_note},
                              titles=args.preview_title or None,
                              projects=args.preview_project or None)
    else:
        data = raw if args.internal else shareable_report(raw)
    encoded = json.dumps(data, indent=2, ensure_ascii=False)
    if args.output:
        destination = Path(args.output).expanduser()
        if destination.exists():
            parser.error("refusing to overwrite an existing diagnostics report")
        with destination.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
    else:
        print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
