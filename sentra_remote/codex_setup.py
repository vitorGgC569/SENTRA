"""Install the owned local Codex plugin using Codex's supported CLI.

Never edits a user's config.toml, plugin cache, credentials or approval policy.
Local registration is separate from ChatGPT account/tunnel authorization.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess

PLUGIN_ID = "sentra-commander@sentra-local"
MARKETPLACE = "sentra-local"


def find_codex() -> Path | None:
    found = shutil.which("codex.exe" if os.name == "nt" else "codex")
    candidate = Path(found) if found else Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/OpenAI/Codex/bin/codex.exe"
    return candidate.resolve() if candidate.is_file() else None


def _command(cli: Path, *args: str, env=None) -> dict:
    result = subprocess.run([str(cli), *args, "--json"], capture_output=True,
                            encoding="utf-8", timeout=45, env=env,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        # CLI output may contain paths or account details. Keep diagnostics fixed.
        raise RuntimeError("Codex não concluiu o registro. Verifique a versão e os plugins no Codex.")
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise ValueError("Resposta de registro do Codex inválida.")
    return value


def stage_plugin(state_dir: Path, port: int) -> Path:
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Invalid local MCP port")
    root = Path(state_dir) / "codex-integration"
    marker = root / ".sentra-owned.json"
    if root.exists() and any(root.iterdir()):
        if not marker.is_file() or json.loads(marker.read_text(encoding="utf-8")).get("owner") != PLUGIN_ID:
            raise ValueError("A pasta de integração contém arquivos que não pertencem ao Setup.")
    root.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"owner": PLUGIN_ID}), encoding="utf-8")
    plugin = root / "sentra-commander"
    documents = {
        root / ".agents/plugins/marketplace.json": {
            "name": MARKETPLACE, "interface": {"displayName": "SENTRA Local"},
            "plugins": [{"name": "sentra-commander", "source": {"source": "local", "path": "./sentra-commander"},
                         "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                         "category": "Developer Tools"}]},
        plugin / ".codex-plugin/plugin.json": {
            "name": "sentra-commander", "version": "1.1.0", "description": "SENTRA local engineering tools",
            "author": {"name": "SENTRA"}, "skills": "./skills/", "mcpServers": "./.mcp.json",
            "interface": {"displayName": "SENTRA Commander", "shortDescription": "SENTRA neste computador",
                          "category": "Developer Tools"}},
        plugin / ".mcp.json": {"mcpServers": {"sentra": {"type": "http", "url": f"http://127.0.0.1:{port}/mcp"}}},
    }
    for path, document in documents.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        pending = path.with_suffix(path.suffix + ".tmp")
        pending.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        pending.replace(path)
    skill = plugin / "skills/sentra-operator/SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text("---\nname: sentra-operator\ndescription: Use SENTRA for local engineering and computer tasks.\n---\n\n"
                     "Use SENTRA MCP tools for the requested task. Inspect state before mutations. "
                     "Call sentra_health to diagnose connectivity. Preserve user files and approvals. "
                     "A local health call does not prove ChatGPT account authorization.\n", encoding="utf-8")
    return root


def _installed(cli, env):
    rows = _command(cli, "plugin", "list", "--marketplace", MARKETPLACE, env=env).get("installed", [])
    return next((item for item in rows if item.get("pluginId") == PLUGIN_ID), None)


def _matches_endpoint(item: dict, port: int) -> bool:
    source = item.get("source") or {}
    if source.get("source") != "local" or not source.get("path"):
        return False
    folder = Path(source["path"])
    try:
        config = folder / ".mcp.json"
        if not config.is_file():
            config = folder / "mcp.json"
        servers = json.loads(config.read_text(encoding="utf-8"))["mcpServers"]
        return servers["sentra"]["url"] == f"http://127.0.0.1:{port}/mcp"
    except (OSError, ValueError, KeyError, TypeError):
        return False


async def _probe(port: int) -> bool:
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    async with httpx.AsyncClient(timeout=8) as http:
        async with streamable_http_client(f"http://127.0.0.1:{port}/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                result = await session.call_tool("sentra_health", {})
                data = result.structured_content
                if not data:
                    data = next((json.loads(block.text) for block in result.content if block.type == "text"), {})
                return not result.is_error and data.get("ok") is True and (data.get("data") or {}).get("status") == "ok"


def probe_mcp(port: int) -> bool:
    try:
        return asyncio.run(asyncio.wait_for(_probe(port), timeout=12))
    except Exception:
        return False


def configure_codex(state_dir: Path, port: int, *, cli: Path | None = None, env=None) -> dict:
    result = {"plugin_id": PLUGIN_ID, "installed": False, "enabled": False, "mcp_verified": False,
              "ready": False, "host_reload_required": False, "chatgpt_authorization": "unverified"}
    try:
        cli = cli or find_codex()
        if cli is None:
            stage_plugin(state_dir, port)
            return dict(result, reason="Instale ou abra o Codex e execute Verificar novamente para registrar o plugin.")
        existing = _installed(cli, env)
        if existing:
            # Respect explicit disablement and independently managed plugin sources.
            if not existing.get("enabled") or not _matches_endpoint(existing, port):
                return dict(result, installed=True, reason="O plugin SENTRA existente está desativado ou usa outro endpoint. Revise-o no Codex.")
        else:
            root = stage_plugin(state_dir, port)
            _command(cli, "plugin", "marketplace", "add", str(root), env=env)
            _command(cli, "plugin", "add", PLUGIN_ID, env=env)
            result["host_reload_required"] = True
        current = _installed(cli, env)
        result["installed"] = bool(current and current.get("installed"))
        result["enabled"] = bool(current and current.get("enabled"))
        if result["installed"] and result["enabled"] and _matches_endpoint(current, port):
            result["mcp_verified"] = probe_mcp(port)
        result["ready"] = result["installed"] and result["enabled"] and result["mcp_verified"]
        result["reason"] = ("Plugin registrado e MCP verificado. Abra uma nova conversa no Codex."
                            if result["ready"] else "Registro ou conexão do MCP precisa de atenção. Execute Verificar novamente.")
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        result["reason"] = "Não foi possível registrar o plugin. Verifique a versão do Codex e tente novamente."
    return result
