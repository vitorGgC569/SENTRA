from pathlib import Path
import json
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def test_resolvenet_relay_presence():
    oma_token = ROOT / ".oma" / "relay-token"
    browser_token = ROOT / ".sentra" / "browser" / "relay-token"
    status = {
        "oma_token_exists": oma_token.is_file(),
        "browser_token_exists": browser_token.is_file(),
        "health": None,
        "health_error": None,
    }
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=3) as response:
            status["health"] = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        status["health_error"] = f"{type(exc).__name__}: {exc}"
    out = ROOT / ".sentra" / "resolvenet-relay-presence.json"
    out.write_text(json.dumps(status, indent=2), encoding="utf-8")
    assert status["oma_token_exists"] or status["browser_token_exists"]
