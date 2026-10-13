"""Provider failures must reach the shell without exposing protected output."""
from sentra_canvas.shell_runtime import CanvasShellRuntime
from sentra_cli.client import ModelClient


def diagnose(journal, prompt="Opa"):
    runtime = CanvasShellRuntime.__new__(CanvasShellRuntime)
    runtime._journal_messages = lambda _: journal
    return runtime._delivery_problem({"conversation_id": "test", "content": prompt})


def entry(role, content, kind="message"):
    return {"role": role, "content": content, "kind": kind}


def test_missing_connector_is_explained_without_private_provider_output():
    reason = diagnose([entry("user", "Opa"),
                       entry("assistant", "connector_not_found secret=private-token C:/private", "provider_error")])
    assert "plugin SENTRA" in reason
    assert "private-token" not in reason and "C:/private" not in reason


def test_model_failure_does_not_get_replaced_by_a_later_turn():
    reason = diagnose([entry("user", "Opa"),
                       entry("assistant", "model_version_unavailable", "provider_error"),
                       entry("user", "Outra mensagem"),
                       entry("assistant", "connector_not_found", "provider_error")])
    assert "modelo" in reason and "não foi enviada" in reason


def test_success_and_unmatched_prompts_do_not_inherit_old_errors():
    journal = [entry("user", "Primeira"), entry("assistant", "connector_not_found", "provider_error"),
               entry("user", "Opa"), entry("assistant", "Olá")]
    assert diagnose(journal) is None
    assert diagnose(journal, "Não registrado") is None


def test_unknown_provider_failure_remains_private():
    reason = diagnose([entry("user", "Opa"),
                       entry("assistant", "Bearer private-token; traceback", "provider_error")])
    assert "não confirmou" in reason and "private-token" not in reason


def test_missing_connector_is_a_preflight_rejection_for_both_stream_error_shapes():
    for shape in [
        {"type": "error", "error": {"code": "connector_not_found", "message": "No connector row"}},
        {"type": "response.failed", "response": {"error": {"code": "connector_not_found", "message": "No connector row"}}},
    ]:
        detail, rejected = ModelClient._stream_failure_detail(shape)
        assert rejected and detail == "connector_not_found: No connector row"
    _, rejected = ModelClient._stream_failure_detail({"type": "error", "error": {"code": "unknown_error"}})
    assert not rejected
