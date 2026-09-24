from __future__ import annotations

from orchestrator.configuration import resolve_codex_web_model, resolve_gateway_admin_token
from sentra_remote.product import ProductPaths, ProductSettings


def test_codex_web_model_resolution_precedence(tmp_path, monkeypatch) -> None:
    state = tmp_path / "state"
    monkeypatch.setenv("SENTRA_STATE_DIR", str(state))
    monkeypatch.delenv("SENTRA_CODEX_WEB_MODEL", raising=False)

    paths = ProductPaths.default()
    ProductSettings(web_model_name="sentra/chatgpt-web/saved").save(paths.settings)

    assert resolve_codex_web_model({"model_name": None}) == "sentra/chatgpt-web/saved"

    monkeypatch.setenv("SENTRA_CODEX_WEB_MODEL", "sentra/chatgpt-web/env")
    assert resolve_codex_web_model({"model_name": None}) == "sentra/chatgpt-web/env"

    assert resolve_codex_web_model({
        "model_name": "sentra/chatgpt-web/explicit",
    }) == "sentra/chatgpt-web/explicit"


def test_gateway_admin_token_uses_env_then_private_state(tmp_path, monkeypatch) -> None:
    state = tmp_path / "state"
    monkeypatch.setenv("SENTRA_STATE_DIR", str(state))
    monkeypatch.delenv("SENTRA_GATEWAY_ADMIN_TOKEN", raising=False)

    first = resolve_gateway_admin_token({})
    second = resolve_gateway_admin_token({})
    assert first == second
    assert len(first) >= 40
    assert (state / "web-models" / "gateway-admin.token").is_file()

    monkeypatch.setenv("SENTRA_GATEWAY_ADMIN_TOKEN", "explicit-admin-token-for-tests")
    assert resolve_gateway_admin_token({}) == "explicit-admin-token-for-tests"


def test_gateway_admin_token_env_name_is_validated(monkeypatch) -> None:
    monkeypatch.delenv("SENTRA_GATEWAY_ADMIN_TOKEN", raising=False)
    try:
        resolve_gateway_admin_token({"gateway_admin_token_env": "BAD\nNAME"})
    except ValueError as exc:
        assert "gateway_admin_token_env" in str(exc)
    else:
        raise AssertionError("invalid admin-token env name must be rejected")
