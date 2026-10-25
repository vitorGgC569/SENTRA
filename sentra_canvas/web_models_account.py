"""Owner-authenticated control of the managed ChatGPT login window."""
import json
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _host_account_control(action="status"):
    if action not in {"status", "login"}:
        raise ValueError("invalid account action")
    descriptor = Path.home() / ".codex-chatgpt-web" / "runtime" / "launcher-browser.json"
    if not descriptor.is_file():
        return {"available": False, "authenticated": False, "status": "unavailable"}
    if descriptor.stat().st_size > 262144:
        raise ValueError("invalid managed browser descriptor")
    data = json.loads(descriptor.read_text(encoding="utf-8"))
    if data.get("version") != 3 or data.get("kind") != "codex-web-gpt-launcher" or data.get("sentraManaged") is not True:
        raise PermissionError("browser is not managed by SENTRA")
    control = data.get("control") or {}
    url, token = control.get("endpoint", ""), control.get("token", "")
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port
            or parsed.path not in {"", "/"} or parsed.username or parsed.password or parsed.query or parsed.fragment
            or not isinstance(token, str) or not 40 <= len(token) <= 128):
        raise ValueError("invalid managed browser control")
    request = urllib.request.Request(url.rstrip("/") + "/v1/sentra/account",
        data=json.dumps({"action": action}).encode("utf-8"),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    with opener.open(request, timeout=15) as response:
        result = json.loads(response.read(8192))
    if not isinstance(result, dict) or not isinstance(result.get("authenticated"), bool):
        raise RuntimeError("invalid managed account response")
    return {"available": True, "authenticated": result["authenticated"],
            "status": str(result.get("status", "unknown"))[:40],
            "login_open": result.get("login_open") is True,
            "saved_chats": result.get("saved_chats") is True}


def account_control(action="status", *, paths=None):
    if action not in {"status", "login", "setup"}:
        raise ValueError("invalid account action")
    from sentra_remote.product import ProductPaths
    from sentra_remote.account_setup import start_account_setup, setup_status
    if paths is None:
        import sys
        install = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1] / "dist"
        paths = ProductPaths.default(install)
    if action == "setup":
        return {"available": True, "authenticated": False, "setup": start_account_setup(paths)}
    result = _host_account_control(action)
    result["setup"] = setup_status(paths)
    return result
