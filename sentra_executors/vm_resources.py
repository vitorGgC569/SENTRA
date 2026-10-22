"""Read-only VirtualBox resource measurement and host-safe limit plans.

Calls the public VirtualBox client API (``status`` and ``run``). Does not edit
``virtualbox_*.py`` and does not start, stop, delete, or resize a VM. A plan
is a recommendation. It is not a Grant and it does not authorize an effect.
"""
from __future__ import annotations

import re
from typing import Any

_METRIC_LINE = re.compile(r"^\s*([A-Za-z0-9_./:-]+)\s+([+-]?\d+(?:\.\d+)?)")
_METRIC_PREFIXES = ("CPU/Load", "RAM/Usage", "Guest/CPU", "Guest/RAM")


def default_client():
    """Build a client from the public VirtualBox API. Does not touch a VM."""
    from sentra_executors.virtualbox_vm import VirtualBoxClient

    return VirtualBoxClient()


def _as_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"missing {name}")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip().lstrip("-").isdigit():
        number = int(value.strip())
    else:
        raise ValueError(f"invalid {name}")
    return number


def _execution_cap(value: Any) -> int:
    if value is None or value == "":
        return 100
    number = _as_int(value, "CPUExecutionCap")
    if not 0 <= number <= 100:
        raise ValueError("cpu execution cap out of range")
    return number


def _stdout(result: Any) -> str:
    if isinstance(result, str):
        return result
    return str(getattr(result, "stdout", "") or "")


def parse_metrics(text: str) -> dict[str, float]:
    """Keep numeric CPU/RAM series only. Drop paths and other text."""
    found: dict[str, float] = {}
    for line in str(text or "").splitlines():
        match = _METRIC_LINE.match(line.strip())
        if not match:
            continue
        name = match.group(1)
        if not any(name.startswith(prefix) for prefix in _METRIC_PREFIXES):
            continue
        found[name] = float(match.group(2))
    return found


def _ceiling(ceiling: dict[str, Any] | None) -> tuple[int, float, float, int]:
    data = dict(ceiling or {})
    reserve = data.get("host_reserve_mb", 2048)
    max_cpu = data.get("max_cpu_percent", 85)
    max_ram = data.get("max_ram_percent", 80)
    hot_cap = data.get("hot_execution_cap", 40)
    if type(reserve) is not int or reserve < 512:
        raise ValueError("host_reserve_mb must be an int >= 512")
    if isinstance(max_cpu, bool) or not isinstance(max_cpu, (int, float)) or not 1 <= float(max_cpu) <= 95:
        raise ValueError("max_cpu_percent must stay inside 1..95")
    if isinstance(max_ram, bool) or not isinstance(max_ram, (int, float)) or not 1 <= float(max_ram) <= 90:
        raise ValueError("max_ram_percent must stay inside 1..90")
    if type(hot_cap) is not int or not 10 <= hot_cap <= 100:
        raise ValueError("hot_execution_cap must be an int inside 10..100")
    return reserve, float(max_cpu), float(max_ram), hot_cap


def measure(client: Any, binding: Any) -> dict[str, Any]:
    """Read configured CPU, RAM, and execution cap for one owned VM.

    Uses ``client.status``, which is the public read-only identity check, then
    one ``metrics query`` with ``physical=False``. Mutating VBoxManage verbs
    are refused if a client wrapper reports them.
    """
    info = client.status(binding)
    if not isinstance(info, dict):
        raise ValueError("vm status must be an object")
    vm_id = str(getattr(binding, "vm_id", "") or "")
    if not vm_id or str(info.get("UUID", "")).lower() != vm_id.lower():
        raise ValueError("vm identity mismatch")
    marker = getattr(binding, "marker", None)
    if marker is not None and info.get("description") != marker:
        raise ValueError("vm marker mismatch")
    configured: dict[str, Any] = {
        "vm_id": vm_id,
        "state": str(info.get("VMState") or "unknown"),
        "cpus": _as_int(info.get("cpus"), "cpus"),
        "memory_mb": _as_int(info.get("memory"), "memory"),
        "cpu_execution_cap": _execution_cap(info.get("CPUExecutionCap", 100)),
    }
    if configured["cpus"] < 1 or configured["memory_mb"] < 1:
        raise ValueError("vm cpu and memory must be positive")
    metrics: dict[str, Any] = {"available": False, "series": {}, "authorizes_effects": False}
    try:
        # physical=False is required. Never retry the query as a physical call.
        result = client.run("metrics", "query", vm_id, physical=False)
    except Exception:
        result = None
    if result is not None:
        text = _stdout(result)
        metrics = {
            "available": True,
            "series": parse_metrics(text),
            "authorizes_effects": False,
        }
    return {
        **configured,
        "metrics": metrics,
        "authorizes_effects": False,
        "mutated": False,
    }


def plan_limits(
    *,
    configured: dict[str, Any],
    host: dict[str, Any],
    ceiling: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recommend a VM cap that leaves the host usable.

    Memory size and CPU count are reported, not changed. Lowering the CPU
    execution cap is a recommendation only; this function never calls
    VBoxManage. The recommended cap stays inside 10..100 so the guest is not
    stalled and the host is not pinned.
    """
    if not isinstance(configured, dict) or not isinstance(host, dict):
        raise TypeError("configured and host must be objects")
    reserve, max_cpu, max_ram, hot_cap = _ceiling(ceiling)
    if "available_mb" not in host:
        raise ValueError("host.available_mb is required")
    available = host.get("available_mb")
    if type(available) is not int or available < 0:
        raise ValueError("host.available_mb must be a non-negative int")
    cpus = _as_int(configured.get("cpus"), "cpus")
    memory_mb = _as_int(configured.get("memory_mb"), "memory_mb")
    cap = _execution_cap(configured.get("cpu_execution_cap", 100))
    if cpus < 1 or memory_mb < 1:
        raise ValueError("configured cpu and memory must be positive")
    reasons: list[str] = []
    cpu_percent = host.get("cpu_percent")
    ram_percent = host.get("ram_percent")
    hot = False
    if cpu_percent is not None:
        if isinstance(cpu_percent, bool) or not isinstance(cpu_percent, (int, float)):
            raise ValueError("host.cpu_percent must be a number or null")
        if not 0 <= float(cpu_percent) <= 100:
            raise ValueError("host.cpu_percent out of range")
        if float(cpu_percent) >= max_cpu:
            hot = True
            reasons.append("host cpu is hot")
    if ram_percent is not None:
        if isinstance(ram_percent, bool) or not isinstance(ram_percent, (int, float)):
            raise ValueError("host.ram_percent must be a number or null")
        if not 0 <= float(ram_percent) <= 100:
            raise ValueError("host.ram_percent out of range")
        if float(ram_percent) >= max_ram:
            hot = True
            reasons.append("host ram percent is hot")
    room = available - reserve
    admit_new_vm = room >= 1024
    if memory_mb > max(room, 0):
        admit_new_vm = False
        reasons.append("configured memory exceeds the host reserve; not applied")
    if available < reserve:
        hot = True
        admit_new_vm = False
        reasons.append("host reserve is already thin")
    host_cpus = host.get("cpu_count")
    if host_cpus is not None:
        host_cpus = _as_int(host_cpus, "cpu_count")
        if host_cpus > 1 and cpus >= host_cpus:
            admit_new_vm = False
            reasons.append("vm would consume every host core; cpu count is not changed")
    planned_cap = cap
    if cap < 10:
        planned_cap = 10
        reasons.append("execution cap below 10 stalls the guest; recommendation only")
    if hot and planned_cap > hot_cap:
        planned_cap = hot_cap
        reasons.append("lower execution cap while the host is hot; recommendation only")
    planned_cap = max(10, min(100, int(planned_cap)))
    return {
        "cpus": cpus,
        "memory_mb": memory_mb,
        "cpu_execution_cap": planned_cap,
        "cap_change_recommended": planned_cap != cap,
        "memory_change_applied": False,
        "cpu_count_change_applied": False,
        "admit_new_vm": admit_new_vm,
        "reasons": reasons,
        "authorizes_effects": False,
        "mutated": False,
    }


_ORDER_FIELDS = ("run_id", "work_item_id", "operation_id", "grant_id", "owner", "vm_id")
_OBSERVED_STATES = {"running", "paused", "poweroff", "saved"}


def _missing_order_fields(order: Any) -> list[str]:
    if not isinstance(order, dict):
        return list(_ORDER_FIELDS)
    missing = []
    for field in _ORDER_FIELDS:
        value = order.get(field)
        if not isinstance(value, str) or not value.strip():
            missing.append(field)
    return missing


def _shown_plan(plan: dict[str, Any]) -> dict[str, Any]:
    cap = int(plan["cpu_execution_cap"])
    if not 10 <= cap <= 100:
        raise ValueError("execution cap must stay inside 10..100")
    return {
        "cpus": int(plan["cpus"]),
        "memory_mb": int(plan["memory_mb"]),
        "cpu_execution_cap": cap,
    }


def prepare_authorized_change(
    *,
    plan: dict[str, Any],
    order: Any,
    observed: dict[str, Any],
    admission: dict[str, Any],
) -> dict[str, Any]:
    """Verify owner, UUID, state, and load. Do not call VBoxManage.

    A passing check returns a receipt and the previous cap as rollback.
    ``executed`` stays false until a later controlled proof.
    """
    if not isinstance(plan, dict) or not isinstance(observed, dict) or not isinstance(admission, dict):
        raise TypeError("plan, observed, and admission must be objects")
    for key in ("cpus", "memory_mb", "cpu_execution_cap"):
        if key not in plan:
            raise ValueError(f"plan.{key} is required")
    shown = _shown_plan(plan)
    missing = _missing_order_fields(order)
    if missing:
        return {
            "ready": False, "executed": False, "applied": False, "refused": True,
            "reason": "sem ordem", "missing_order_fields": missing, "plan": shown,
            "rollback": None, "receipt": None, "authorizes_effects": False, "mutated": False,
        }
    owner = str(order.get("owner") or "")
    vm_id = str(order.get("vm_id") or "").lower()
    observed_vm = str(observed.get("vm_id") or "").lower()
    state = str(observed.get("state") or "")
    reasons: list[str] = []
    if owner != str(observed.get("owner") or ""):
        reasons.append("owner mismatch")
    if not vm_id or vm_id != observed_vm:
        reasons.append("uuid mismatch")
    if state not in _OBSERVED_STATES:
        reasons.append("state mismatch")
    try:
        observed_memory = int(observed["memory_mb"])
        observed_cpus = int(observed["cpus"])
        previous_cap = int(observed["cpu_execution_cap"])
    except (TypeError, ValueError, KeyError):
        reasons.append("observed shape")
        observed_memory = observed_cpus = previous_cap = 0
    if not reasons and (observed_memory != shown["memory_mb"] or observed_cpus != shown["cpus"]):
        reasons.append("memory or cpu count would change")
    if not admission.get("admitted"):
        reasons.append("admission refused")
    host = observed.get("host") if isinstance(observed.get("host"), dict) else {}
    rollback = {
        "cpu_execution_cap": previous_cap,
        "memory_mb": observed_memory,
        "cpus": observed_cpus,
    }
    ready = not reasons
    receipt = None
    if ready:
        receipt = {
            "run_id": order.get("run_id"),
            "work_item_id": order.get("work_item_id"),
            "operation_id": order.get("operation_id"),
            "grant_id": order.get("grant_id"),
            "owner": owner,
            "vm_id": observed_vm,
            "state": state,
            "load": {
                "ram_percent": (host or {}).get("ram_percent"),
                "available_mb": (host or {}).get("available_mb"),
                "cpu_percent": (host or {}).get("cpu_percent"),
            },
            "previous_cap": previous_cap,
            "planned_cap": shown["cpu_execution_cap"],
            "executed": False,
        }
    return {
        "ready": ready,
        "executed": False,
        "applied": False,
        "refused": not ready,
        "reason": "recibo preparado; prova controlada ainda nao executada" if ready else "; ".join(reasons),
        "missing_order_fields": [],
        "plan": shown,
        "rollback": rollback,
        "receipt": receipt,
        "authorizes_effects": False,
        "mutated": False,
    }


def _refuse(plan: dict[str, Any], reason: str, *, missing: list[str] | None = None) -> dict[str, Any]:
    return {
        "ready": False, "executed": False, "applied": False, "refused": True,
        "reason": reason, "missing_order_fields": missing or [], "plan": plan,
        "rollback": None, "receipt": None, "authorizes_effects": False, "mutated": False,
    }


def _write_receipt(state_root: Any, operation_id: str, payload: dict[str, Any]) -> str:
    import json
    import os
    import tempfile
    from pathlib import Path

    root = Path(state_root) / "vm-cap-receipts"
    root.mkdir(parents=True, exist_ok=True)
    target = root / (operation_id + ".json")
    fd, temp = tempfile.mkstemp(prefix=".cap-", suffix=".tmp", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return str(target)


def apply_authorized_cap(
    client: Any,
    binding: Any,
    plan: dict[str, Any],
    *,
    host: dict[str, Any],
    surfaces: dict[str, Any],
    ceiling: Any,
    state_root: Any,
) -> dict[str, Any]:
    """Apply a CPU execution cap through VirtualBoxClient after central admission.

    Four strings are not an order. The current central effect context must
    checkpoint, and its reserved intent must name this VM, capability
    ``vm:manage``, action ``resource.cap``, an inspected workload, and a
    controlled proof. Identity comes from ``client.status``. The receipt and
    rollback are written before ``controlvm``. A real VBoxManage run still
    requires that proof on the reserved intent; this function does not invent it.
    """
    from sentra_executors.virtualbox_vm import VirtualBoxClient
    from sentra_runtime.effect_boundary import current_effect_context
    from orchestrator.resources import evaluate_admission

    if not isinstance(client, VirtualBoxClient):
        raise TypeError("authorized cap requires VirtualBoxClient")
    if not isinstance(plan, dict):
        raise TypeError("plan must be an object")
    for key in ("cpus", "memory_mb", "cpu_execution_cap"):
        if key not in plan:
            raise ValueError(f"plan.{key} is required")
    shown = _shown_plan(plan)
    context = current_effect_context.get()
    if context is None or not hasattr(context, "checkpoint"):
        return _refuse(shown, "autoridade central ausente")
    try:
        context.checkpoint()
    except Exception as exc:
        return _refuse(shown, "autoridade central recusou: " + type(exc).__name__)
    request = getattr(context, "request", None)
    receipt = getattr(context, "receipt", None)
    if request is None or receipt is None:
        return _refuse(shown, "autoridade central incompleta")
    arguments = getattr(request, "arguments", None) or {}
    owner = str(getattr(receipt, "owner", "") or "")
    operation_id = str(getattr(receipt, "operation_id", "") or "")
    if not owner or not operation_id or owner != str(getattr(request, "principal_id", "") or ""):
        return _refuse(shown, "owner mismatch")
    if getattr(request, "capability_id", None) != "vm:manage":
        return _refuse(shown, "capability mismatch")
    if arguments.get("action") != "resource.cap":
        return _refuse(shown, "action mismatch")
    if str(arguments.get("vm_id") or "").lower() != str(getattr(binding, "vm_id", "") or "").lower():
        return _refuse(shown, "uuid mismatch")
    if getattr(request, "work_item_id", None) in (None, "") or getattr(receipt, "run_id", None) in (None, ""):
        return _refuse(shown, "run ou work item ausente na autoridade")
    proof = arguments.get("controlled_proof") is True and arguments.get("workload_inspected") is True
    if not proof:
        body = {
            "run_id": receipt.run_id,
            "work_item_id": request.work_item_id,
            "operation_id": operation_id,
            "fencing_token": getattr(receipt, "fencing_token", None),
            "owner": owner,
            "vm_id": str(binding.vm_id).lower(),
            "executed": False,
            "rollback": None,
        }
        path = _write_receipt(state_root, operation_id, body)
        return {
            "ready": True, "executed": False, "applied": False, "refused": False,
            "reason": "prova controlada ou workload inspecionado ausente na autoridade",
            "missing_order_fields": [], "plan": shown, "rollback": None,
            "receipt": body, "receipt_path": path, "authorizes_effects": False, "mutated": False,
        }
    try:
        info = client.status(binding)
    except Exception as exc:
        return _refuse(shown, "identidade da vm indisponivel: " + type(exc).__name__)
    if str(info.get("UUID") or "").lower() != str(binding.vm_id).lower():
        return _refuse(shown, "uuid mismatch")
    state = str(info.get("VMState") or "")
    if state != "running":
        return _refuse(shown, "state mismatch")
    try:
        observed_cpus = int(info.get("cpus"))
        observed_memory = int(info.get("memory"))
        previous_cap = int(info.get("CPUExecutionCap") or 100)
    except (TypeError, ValueError, KeyError):
        return _refuse(shown, "observed shape")
    if observed_cpus != shown["cpus"] or observed_memory != shown["memory_mb"]:
        return _refuse(shown, "memory or cpu count would change")
    if not 10 <= previous_cap <= 100:
        return _refuse(shown, "current cap is outside 10..100")
    lowering = shown["cpu_execution_cap"] < previous_cap
    decision = evaluate_admission(
        ceiling=ceiling, host=host, surfaces=surfaces, surface="vm",
        ram_mb=0, cpu_percent=0,
    )
    if not lowering and not decision["allowed"]:
        return _refuse(shown, "admission refused")
    rollback = {
        "cpu_execution_cap": previous_cap,
        "memory_mb": observed_memory,
        "cpus": observed_cpus,
        "command": ["controlvm", str(binding.vm_id), "cpuexecutioncap", str(previous_cap)],
    }
    body = {
        "run_id": receipt.run_id,
        "work_item_id": request.work_item_id,
        "operation_id": operation_id,
        "fencing_token": getattr(receipt, "fencing_token", None),
        "owner": owner,
        "vm_id": str(info.get("UUID")).lower(),
        "state": state,
        "load": {
            "ram_percent": (host or {}).get("ram_percent"),
            "available_mb": (host or {}).get("available_mb"),
            "cpu_percent": (host or {}).get("cpu_percent"),
            "admission_allowed": decision["allowed"],
        },
        "previous_cap": previous_cap,
        "planned_cap": shown["cpu_execution_cap"],
        "rollback": rollback,
        "executed": False,
    }
    if not proof:
        path = _write_receipt(state_root, operation_id, body)
        return {
            "ready": True, "executed": False, "applied": False, "refused": False,
            "reason": "prova controlada ou workload inspecionado ausente na autoridade",
            "missing_order_fields": [], "plan": shown, "rollback": rollback,
            "receipt": body, "receipt_path": path, "authorizes_effects": False, "mutated": False,
        }
    path = _write_receipt(state_root, operation_id, body)
    try:
        client.run(
            "controlvm", str(binding.vm_id), "cpuexecutioncap", str(shown["cpu_execution_cap"]),
            physical=True,
        )
    except Exception as exc:
        body["error"] = type(exc).__name__
        path = _write_receipt(state_root, operation_id, body)
        return {
            "ready": True, "executed": False, "applied": False, "refused": True,
            "reason": "controlvm falhou: " + type(exc).__name__,
            "missing_order_fields": [], "plan": shown, "rollback": rollback,
            "receipt": body, "receipt_path": path, "authorizes_effects": False, "mutated": False,
        }
    body["executed"] = True
    path = _write_receipt(state_root, operation_id, body)
    return {
        "ready": True, "executed": True, "applied": True, "refused": False,
        "reason": "cap aplicado pelo VirtualBoxClient autorizado",
        "missing_order_fields": [], "plan": shown, "rollback": rollback,
        "receipt": body, "receipt_path": path, "authorizes_effects": False, "mutated": False,
    }


def apply_plan(
    client: Any,
    binding: Any,
    plan: dict[str, Any],
    order: Any = None,
    *,
    host: dict[str, Any] | None = None,
    surfaces: dict[str, Any] | None = None,
    ceiling: Any = None,
    state_root: Any = None,
) -> dict[str, Any]:
    """Apply only through the central effect context.

    An absent order does nothing. A dict of ids is not authority. When the
    host sample and state root are present, this delegates to
    :func:`apply_authorized_cap`, which calls ``VirtualBoxClient`` only after
    the central checkpoint and the reserved proof.
    """
    if client is None or binding is None:
        raise ValueError("client and binding are required to name the VM that is not changed")
    if not isinstance(plan, dict):
        raise TypeError("plan must be an object")
    for key in ("cpus", "memory_mb", "cpu_execution_cap"):
        if key not in plan:
            raise ValueError(f"plan.{key} is required")
    shown = _shown_plan(plan)
    if order is None or _missing_order_fields(order):
        return _refuse(
            shown, "sem ordem",
            missing=_missing_order_fields(order) if isinstance(order, dict) else list(_ORDER_FIELDS),
        )
    if host is None or surfaces is None or ceiling is None or state_root is None:
        return _refuse(shown, "autoridade central ausente")
    return apply_authorized_cap(
        client, binding, plan, host=host, surfaces=surfaces, ceiling=ceiling, state_root=state_root,
    )


def measure_and_plan(
    client: Any,
    binding: Any,
    host: dict[str, Any],
    ceiling: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Measure one VM and attach a host-safe plan. Performs no VM write."""
    measured = measure(client, binding)
    plan = plan_limits(configured=measured, host=host, ceiling=ceiling)
    return {
        "measured": measured,
        "plan": plan,
        "mutated": False,
        "authorizes_effects": False,
    }
