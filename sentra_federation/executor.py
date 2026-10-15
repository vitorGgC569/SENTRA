"""Federation receipts and the legacy arithmetic fallback.

Explicit structured plans are executed by task_runtime through the real
installation MachineHost, independent capability grants and durable fences.
This module verifies both contracts. A plain-text arithmetic request retains
the bounded hermetic fallback; other unplanned text stays unresolved rather
than becoming an echoed deliverable. Uncertain operations are never replayed.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

from .errors import FederationDenied

EXECUTOR = "control-plane-work-item"
_MAX_ABS = 10**12
_MAX_EXPRESSION = 80
_SPAN_CHARS = set("0123456789+-*/%() \t")
_CALCULATION_WORDS = frozenset({
    "a", "an", "and", "answer", "apenas", "as", "calcule", "calcula", "calcular",
    "calculo", "cálculo", "calculate", "compute", "da", "das", "de", "deliver",
    "do", "dos", "e", "eh", "entregue", "entrega", "entregar", "favor", "give",
    "igual", "is", "me", "number", "numero", "número", "numeric", "numerico",
    "numérico", "o", "only", "os", "please", "por", "resposta", "result",
    "resultado", "results", "somente", "the", "um", "uma", "valor", "value",
    "what", "é", "quanto",
})
_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.UAdd, ast.USub,
)


class _NotHermetic(Exception):
    """The objective is not one bounded integer expression."""


def resolve_hermetic_arithmetic(objective):
    """Return one exact integer result, or None when the objective is not that."""
    try:
        return _resolve_hermetic_arithmetic(objective)
    except Exception:
        return None


def result_document(*, project_id, task, work_item_id, deliverable):
    resolved = resolve_hermetic_arithmetic(task)
    if resolved is None or not isinstance(deliverable, str) or deliverable != resolved or deliverable == task:
        raise FederationDenied("dot result does not resolve the objective")
    document = {
        "schema": 1,
        "project_id": project_id,
        "task": task,
        "work_item_id": work_item_id,
        "result": {
            "status": "submitted_for_review",
            "summary": f"Dot submitted the numeric result for project {project_id}.",
            "deliverable": deliverable,
        },
    }
    return json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def verify_result_receipt(receipt, *, objective, scope):
    from .task_runtime import EXECUTOR as MACHINE_EXECUTOR, verify_result
    if isinstance(receipt, dict) and receipt.get("executor") == MACHINE_EXECUTOR:
        return verify_result(receipt, objective=objective, scope=scope)
    if not isinstance(receipt, dict) or receipt.get("executor") != EXECUTOR:
        raise FederationDenied("admission is not a dot result")
    if receipt.get("result_ready") is not True or receipt.get("passed") is not True:
        raise FederationDenied("dot result is not ready")
    if receipt.get("automatic_resend") is not False:
        raise FederationDenied("dot result is not ready")
    waiting = receipt.get("work_item_state") == "IN_REVIEW" and receipt.get("remote_state") == "WAITING_EXTERNAL"
    reviewed = (receipt.get("work_item_state") == "COMPLETED" and receipt.get("remote_state") == "SUCCEEDED"
                and receipt.get("review_approved") is True and receipt.get("executed") is True)
    if not waiting and not reviewed:
        raise FederationDenied("dot result is not waiting for review")
    if receipt.get("task") != objective or not receipt.get("project_id"):
        raise FederationDenied("dot result does not match the task")
    document = receipt.get("result_document")
    artifact_id = receipt.get("artifact_id")
    digest = receipt.get("artifact_sha256")
    if not isinstance(document, str) or not isinstance(artifact_id, str) or not isinstance(digest, str):
        raise FederationDenied("dot artifact is missing")
    if hashlib.sha256(document.encode("utf-8")).hexdigest() != digest:
        raise FederationDenied("dot artifact did not verify")
    try:
        parsed = json.loads(document)
    except (TypeError, ValueError) as exc:
        raise FederationDenied("dot artifact is invalid") from exc
    if not isinstance(parsed, dict):
        raise FederationDenied("dot artifact is invalid")
    if parsed.get("task") != objective or parsed.get("project_id") != receipt.get("project_id"):
        raise FederationDenied("dot artifact does not contain the task")
    result = parsed.get("result")
    if not isinstance(result, dict):
        raise FederationDenied("dot artifact has no result")
    deliverable = result.get("deliverable")
    if not isinstance(deliverable, str) or not deliverable:
        raise FederationDenied("dot artifact has no result")
    if deliverable == objective or deliverable == str(objective).strip():
        raise FederationDenied("dot artifact echoes the task")
    resolved = resolve_hermetic_arithmetic(objective)
    if resolved is None or deliverable != resolved:
        raise FederationDenied("dot artifact does not contain the result")
    return digest


def assert_unresolved_receipt(receipt, *, objective, scope=None):
    """An unresolved objective is a receipt, not a delivery."""
    from .task_runtime import EXECUTOR as MACHINE_EXECUTOR, verify_unresolved
    if isinstance(receipt, dict) and receipt.get("executor") == MACHINE_EXECUTOR:
        return verify_unresolved(receipt, objective=objective, scope=scope)
    if not isinstance(receipt, dict) or receipt.get("executor") != EXECUTOR:
        raise FederationDenied("admission is not a dot result")
    if receipt.get("result_ready") is not False or receipt.get("passed") is not False:
        raise FederationDenied("unresolved dot result claimed a delivery")
    if receipt.get("executed") is not False or receipt.get("automatic_resend") is not False:
        raise FederationDenied("unresolved dot result claimed an effect")
    if receipt.get("task") != objective or not receipt.get("project_id"):
        raise FederationDenied("dot result does not match the task")
    if receipt.get("work_item_state") != "REPAIRING":
        raise FederationDenied("unresolved dot result entered review")
    if receipt.get("result_document") or receipt.get("artifact_id") or receipt.get("artifact_sha256"):
        raise FederationDenied("unresolved dot result echoed a deliverable")
    return receipt


def _move(control, owner, operation, state, intent_id, *, result=None, effect_started=False):
    return control.durable.update_operation(
        operation["operation_id"], owner,
        state=state,
        progress={
            "intent_id": intent_id,
            "executed": False,
            "automatic_resend": False,
            "effect_started": bool(effect_started),
            "phase": "waiting_review" if state == "WAITING_EXTERNAL" and effect_started else "waiting_executor",
        },
        result=result,
    )


def _work_item(control, run_id, owner, objective, intent_id, scope, peer):
    return control.create_work_item(
        run_id, owner,
        objective=objective,
        external_key=intent_id,
        required_capabilities=["federation.delegate"],
        metadata={
            "federation": {
                "intent_id": intent_id,
                "project_id": scope["project_id"],
                "scope": scope,
                "peer": peer,
                "task": objective,
                "executor": EXECUTOR,
                "automatic_resend": False,
            }
        },
        side_effect_scope="none",
        execution_policy={
            "require_quality_gate": True,
            "stages": [{"id": "federation-review", "type": "review", "allow_any_authorized": True}],
        },
    )


def _replayed_receipt(operation, item, intent_id):
    if not operation.get("idempotent_replay") and operation.get("state") != "UNCERTAIN":
        return None
    stored = operation.get("result")
    if isinstance(stored, dict) and stored.get("intent_id") == intent_id and _same_open_result(stored, item):
        return stored
    raise FederationDenied("remote execution is incomplete and is not restarted")


def _same_open_result(stored, item):
    if stored.get("work_item_id") != item.get("work_item_id") or stored.get("automatic_resend") is not False:
        return False
    if stored.get("executed") is not False:
        return False
    ready = stored.get("result_ready") is True and stored.get("passed") is True and item.get("state") == "IN_REVIEW"
    unresolved = stored.get("result_ready") is False and stored.get("passed") is False and item.get("state") == "REPAIRING"
    return ready or unresolved


def execute_delegation(control, *, owner, intent_id, objective, scope, grant_id, peer, artifact_dir):
    """Run one Dot task. An existing or uncertain receipt is not executed again."""
    project_id = scope["project_id"]
    run = control.durable.create_run(
        owner,
        workspace=project_id,
        idempotency_key=f"federation:{owner}:{project_id}",
        required_capabilities=["federation.delegate"],
    )
    operation = control.durable.create_operation(
        run["run_id"], owner,
        kind="federation.delegate",
        idempotency_key=intent_id,
        initial_state="QUEUED",
    )
    if operation.get("idempotent_replay") or operation.get("state") == "UNCERTAIN":
        if not isinstance(operation.get("result"), dict):
            raise FederationDenied("remote execution is incomplete and is not restarted")
        item = _work_item(
            control, run["run_id"], owner, objective, intent_id, scope, peer,
        )
        return _replayed_receipt(operation, item, intent_id)
    item = _work_item(control, run["run_id"], owner, objective, intent_id, scope, peer)
    resolved = resolve_hermetic_arithmetic(objective)
    operation = _move(control, owner, operation, "STARTING", intent_id)
    operation = _move(control, owner, operation, "WAITING_EXTERNAL", intent_id)
    try:
        item = control.start_work_item_execution(item["work_item_id"], owner, run_id=run["run_id"])
        if resolved is None:
            item = control.governance.record_quality_gate(
                item["work_item_id"], owner,
                passed=False,
                reason="objective is not a hermetic arithmetic result",
            )
            if item["state"] != "REPAIRING" or item["execution_state"]["quality_gate"]["passed"] is not False:
                raise FederationDenied("unresolved objective did not stay open")
            receipt = _unresolved_receipt(
                intent_id=intent_id, operation=operation, item=item,
                grant_id=grant_id, objective=objective, project_id=project_id,
            )
            _move(control, owner, operation, "WAITING_EXTERNAL", intent_id, result=receipt, effect_started=False)
            return receipt
        document = result_document(
            project_id=project_id, task=objective, work_item_id=item["work_item_id"], deliverable=resolved,
        )
        directory = Path(artifact_dir)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{intent_id}.json"
        target.write_text(document, encoding="utf-8")
        artifact_id = "artifact-" + intent_id.removeprefix("intent-")
        recorded = control.durable.register_artifact(
            run["run_id"], owner, target,
            operation_id=operation["operation_id"],
            mime_type="application/json",
            metadata={"project_id": project_id, "task": objective, "intent_id": intent_id},
            artifact_id=artifact_id,
            expected_sha256=hashlib.sha256(document.encode("utf-8")).hexdigest(),
        )
        control.governance.record_quality_gate(
            item["work_item_id"], owner,
            passed=True, reason="hermetic arithmetic result", evidence=[recorded["artifact_id"]],
        )
        item = control.governance.submit_for_policy(
            item["work_item_id"], owner, evidence=[recorded["artifact_id"]],
        )
    except FederationDenied:
        _move(control, owner, operation, "FAILED", intent_id)
        raise
    except Exception as exc:
        _move(control, owner, operation, "FAILED", intent_id)
        raise FederationDenied("remote execution refused") from exc
    if item["state"] != "IN_REVIEW":
        _move(control, owner, operation, "FAILED", intent_id)
        raise FederationDenied("dot result did not reach review")
    receipt = {
        "intent_id": intent_id,
        "operation_id": operation["operation_id"],
        "work_item_id": item["work_item_id"],
        "run_id": item["run_id"],
        "grant_id": grant_id,
        "executed": False,
        "result_ready": True,
        "passed": True,
        "automatic_resend": False,
        "executor": EXECUTOR,
        "task": objective,
        "project_id": project_id,
        "result_document": document,
        "artifact_id": recorded["artifact_id"],
        "artifact_sha256": recorded["sha256"],
        "artifact_size": recorded["size_bytes"],
        "resource_uri": recorded["resource_uri"],
        "remote_state": "WAITING_EXTERNAL",
        "work_item_state": "IN_REVIEW",
    }
    _move(control, owner, operation, "WAITING_EXTERNAL", intent_id, result=receipt, effect_started=True)
    return receipt


def _unresolved_receipt(*, intent_id, operation, item, grant_id, objective, project_id):
    return {
        "intent_id": intent_id,
        "operation_id": operation["operation_id"],
        "work_item_id": item["work_item_id"],
        "run_id": item["run_id"],
        "grant_id": grant_id,
        "executed": False,
        "result_ready": False,
        "passed": False,
        "automatic_resend": False,
        "executor": EXECUTOR,
        "task": objective,
        "project_id": project_id,
        "remote_state": "WAITING_EXTERNAL",
        "work_item_state": item["state"],
    }


def _resolve_hermetic_arithmetic(objective):
    if not isinstance(objective, str):
        return None
    text = objective.strip().replace("\r", " ").replace("\n", " ")
    if not text or len(text) > 4000:
        return None
    if any(ord(ch) < 32 and ch not in "\t" for ch in text):
        return None
    spans = _arithmetic_spans(text)
    if len(spans) != 1:
        return None
    expression = spans[0]
    if len(expression) > _MAX_EXPRESSION:
        return None
    start = text.find(expression)
    outside = text[:start] + text[start + len(expression):]
    words = re.findall(r"[^\W\d_]+", outside)
    if any(word.casefold() not in _CALCULATION_WORDS for word in words):
        return None
    return str(_evaluate(expression))


def _arithmetic_spans(text):
    found = []
    index = 0
    limit = len(text)
    while index < limit:
        if not _span_start(text, index) or _glued_before(text, index):
            index += 1
            continue
        end = index + 1
        while end < limit and text[end] in _SPAN_CHARS:
            end += 1
        stop = end
        while stop > index and text[stop - 1] in " \t":
            stop -= 1
        if stop == end and end < limit and (text[end].isalnum() or text[end] in "._,"):
            index = end
            continue
        chunk = text[index:stop].strip()
        if _has_binary_operator(chunk):
            found.append(chunk)
            if len(found) > 1:
                return found
        index = end
    return found


def _span_start(text, index):
    char = text[index]
    if char.isdigit() or char == "(":
        return True
    return (
        char == "-"
        and index + 1 < len(text)
        and (text[index + 1].isdigit() or text[index + 1] == "(")
        and (index == 0 or text[index - 1] in " \t([+*/%")
    )


def _glued_before(text, index):
    return index > 0 and (text[index - 1].isalnum() or text[index - 1] in "._,")


def _has_binary_operator(chunk):
    previous = ""
    for char in chunk:
        if char in "+*/%":
            return True
        if char == "-" and previous not in {"", "+", "-", "*", "/", "%", "(", " "}:
            return True
        if not char.isspace():
            previous = char
    return False


def _evaluate(expression):
    if len(expression) > _MAX_EXPRESSION:
        raise _NotHermetic()
    tree = ast.parse(expression, mode="eval")
    nodes = list(ast.walk(tree))
    if len(nodes) > 32 or any(type(node) not in _ALLOWED_NODES for node in nodes):
        raise _NotHermetic()
    return _eval_node(tree.body, 0)


def _eval_node(node, depth):
    if depth > 16:
        raise _NotHermetic()
    if isinstance(node, ast.Constant):
        if type(node.value) is not int:
            raise _NotHermetic()
        return _fit(node.value)
    if isinstance(node, ast.UnaryOp):
        value = _eval_node(node.operand, depth + 1)
        if isinstance(node.op, ast.UAdd):
            return _fit(value)
        if isinstance(node.op, ast.USub):
            return _fit(-value)
        raise _NotHermetic()
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, depth + 1)
        right = _eval_node(node.right, depth + 1)
        if isinstance(node.op, ast.Add):
            return _fit(left + right)
        if isinstance(node.op, ast.Sub):
            return _fit(left - right)
        if isinstance(node.op, ast.Mult):
            return _mul(left, right)
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)):
            if right == 0 or (isinstance(node.op, ast.Div) and left % right != 0):
                raise _NotHermetic()
            return _fit(left // right if not isinstance(node.op, ast.Mod) else left % right)
        if isinstance(node.op, ast.Pow):
            return _pow(left, right)
        raise _NotHermetic()
    raise _NotHermetic()


def _fit(value):
    if type(value) is not int or abs(value) > _MAX_ABS:
        raise _NotHermetic()
    return value


def _mul(left, right):
    if left != 0 and abs(right) > _MAX_ABS // abs(left):
        raise _NotHermetic()
    return _fit(left * right)


def _pow(left, right):
    if type(right) is not int or right < 0 or right > 12:
        raise _NotHermetic()
    value = 1
    for _ in range(right):
        value = _mul(value, left)
    return value
