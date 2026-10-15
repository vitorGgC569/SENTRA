"""One admission for SENTRA providers and CLIs.

The catalog reports presence. It does not authenticate, send a prompt, or
treat an open window as a model response. An effect still needs a current
Run, WorkItem, Operation and Grant. An UNCERTAIN operation is not resent.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path
from typing import Any, Mapping

AUTHORITY_FIELDS = (
    "owner",
    "run_id",
    "work_item_id",
    "operation_id",
    "grant_id",
    "agent_id",
)
CLI_LANES = (
    {
        "id": "sentra-cli",
        "kind": "cli",
        "model": "sentra/chatgpt-web/gpt-6",
        "effort": "high",
        "executables": ("sentra-cli.exe", "sentra-cli"),
    },
    {
        "id": "opencode",
        "kind": "cli",
        "model": "opencode/muse-spark-1.3-contributor-free#high",
        "effort": "high",
        "executables": ("opencode.exe", "opencode"),
    },
    {
        "id": "codex",
        "kind": "cli",
        "model": "sentra/codex/current",
        "effort": "high",
        "executables": ("codex.exe", "codex"),
    },
)
_UNCERTAIN: set[str] = set()


class FleetAdmissionError(PermissionError):
    pass


def _token(value: Any, field: str) -> str:
    if not isinstance(value, str) or "\0" in value or not value or value != value.strip():
        raise ValueError(f"invalid {field}")
    if len(value) > 128:
        raise ValueError(f"invalid {field}")
    return value


def _authority(raw: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        raise ValueError("fleet admission requires an authority binding")
    return {field: _token(raw.get(field), field) for field in AUTHORITY_FIELDS}


def note_uncertain_effect(operation_id: str) -> None:
    _UNCERTAIN.add(_token(operation_id, "operation_id"))


def claim_effect(operation_id: str) -> None:
    token = _token(operation_id, "operation_id")
    if token in _UNCERTAIN:
        raise FleetAdmissionError("UNCERTAIN operation is not resent")


def uncertain_resend_block(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    state = str(item.get("delivery_state") or item.get("state") or "").upper()
    operation_id = item.get("operation_id")
    remembered = isinstance(operation_id, str) and operation_id in _UNCERTAIN
    if state != "UNCERTAIN" and item.get("execution_uncertain") is not True and not remembered:
        return None
    if isinstance(operation_id, str) and operation_id.strip():
        note_uncertain_effect(operation_id.strip())
    return {
        "_scheduler_error": "UNCERTAIN delivery is not resent",
        "_scheduler_phase": "refused",
        "resend": False,
        "provider": str(item.get("provider") or ""),
        "_scheduler_item": item,
    }


def _file_exists(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _cli_installed(executables: tuple[str, ...], extras: tuple[Path, ...] = ()) -> bool:
    for name in executables:
        found = shutil.which(name)
        if found and _file_exists(Path(found)):
            return True
    return any(_file_exists(path) for path in extras)


def _opencode_extras() -> tuple[Path, ...]:
    appdata = os.environ.get("APPDATA", "")
    if not appdata:
        return ()
    return (Path(appdata) / "npm" / "node_modules" / "@opencode" / "cli" / "bin" / "opencode.exe",)


def _codex_extras() -> tuple[Path, ...]:
    local = os.environ.get("LOCALAPPDATA", "")
    home = Path.home()
    candidates = [home / "AppData" / "Local" / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe"]
    if local:
        candidates.append(Path(local) / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe")
    return tuple(candidates)


def antigravity_gui_paths() -> tuple[Path, ...]:
    paths = [Path.home() / "AppData" / "Local" / "Programs" / "antigravity" / "Antigravity.exe"]
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        paths.append(Path(local) / "Programs" / "antigravity" / "Antigravity.exe")
    return tuple(paths)


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def probe_antigravity(observation: Mapping[str, Any] | None = None, *, gui_paths: tuple[Path, ...] | None = None) -> dict[str, Any]:
    """Report Antigravity without launching it.

    A verified non-interactive inference is an observation that already carries
    its own Run binding, process proof and receipt. The graphical executable
    never satisfies that observation.
    """
    gui = any(_file_exists(path) for path in (gui_paths if gui_paths is not None else antigravity_gui_paths()))
    payload = observation if isinstance(observation, Mapping) else None
    verified = _noninteractive_verified(payload)
    if verified:
        availability = "verified-noninteractive"
        reason = "noninteractive inference observation carries a verified receipt"
    elif gui:
        availability = "unavailable"
        reason = (
            "Antigravity is installed as a graphical application; "
            "opening the window is not a verified non-interactive inference"
        )
    elif payload:
        availability = "unavailable"
        reason = "Antigravity non-interactive observation was not a verified inference"
    else:
        availability = "unavailable"
        reason = "Antigravity non-interactive inference contract is absent"
    return {
        "id": "antigravity",
        "kind": "provider",
        "model": None,
        "installed_gui": gui,
        "installed": gui,
        "authenticated": "not-checked",
        "inference_verified": verified,
        "availability": availability,
        "reason": reason,
        "gui_launch_counts_as_inference": False,
        "effect_allowed": verified,
    }


def _noninteractive_verified(observation: Mapping[str, Any] | None) -> bool:
    if observation is None:
        return False
    if observation.get("gui_launch") is True:
        return False
    if observation.get("kind") != "noninteractive-inference":
        return False
    if observation.get("process_verified") is not True or observation.get("verified") is not True:
        return False
    if observation.get("execution_uncertain") is not False:
        return False
    if not _sha256(observation.get("stdout_sha256")):
        return False
    try:
        _token(observation.get("operation_id"), "operation_id")
        _token(observation.get("work_item_id"), "work_item_id")
        _token(observation.get("grant_id"), "grant_id")
        _token(observation.get("run_id"), "run_id")
    except ValueError:
        return False
    model = observation.get("model")
    if not isinstance(model, str) or not model.strip():
        return False
    lowered = model.strip().lower()
    if lowered in {"antigravity.exe", "gui", "antigravity-app"}:
        return False
    return True


def _web_lanes(root: Path) -> list[dict[str, Any]]:
    module_path = root / "integrations" / "codex_chatgpt_web" / "lane.py"
    spec = importlib.util.spec_from_file_location("codex_chatgpt_web_lane", module_path)
    if spec is None or spec.loader is None:
        raise ImportError("chatgpt web lane is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    lanes = module.web_provider_lanes(root)
    if not isinstance(lanes, list):
        raise ValueError("web provider lanes are unavailable")
    return lanes


def _cli_lane(spec: Mapping[str, Any]) -> dict[str, Any]:
    extras: tuple[Path, ...] = ()
    if spec["id"] == "opencode":
        extras = _opencode_extras()
    elif spec["id"] == "codex":
        extras = _codex_extras()
    installed = _cli_installed(tuple(spec["executables"]), extras)
    return {
        "id": spec["id"],
        "kind": "cli",
        "model": spec["model"],
        "effort": spec["effort"],
        "installed": installed,
        "authenticated": "not-checked",
        "inference_verified": False,
        "availability": "present-unverified" if installed else "unavailable",
        "reason": (
            "executable is present; authentication and inference are not verified"
            if installed else "CLI executable was not found"
        ),
        "gui_launch_counts_as_inference": False,
        "effect_allowed": installed,
    }


def describe_local_fleet(root: Path | None = None, *, antigravity_observation: Mapping[str, Any] | None = None,
                          gui_paths: tuple[Path, ...] | None = None) -> dict[str, Any]:
    base = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    lanes: list[dict[str, Any]] = [_cli_lane(spec) for spec in CLI_LANES]
    try:
        for lane in _web_lanes(base):
            lane = dict(lane)
            lane["effect_allowed"] = lane.get("availability") == "present-unverified"
            lanes.append(lane)
    except (OSError, ValueError, ImportError, AttributeError) as exc:
        for lane_id, prefix in (("chatgpt-web", "sentra/chatgpt-web/"), ("gemini-web", "sentra/gemini-web/")):
            lanes.append({
                "id": lane_id,
                "kind": "provider",
                "model_prefix": prefix,
                "installed": False,
                "authenticated": "not-checked",
                "inference_verified": False,
                "availability": "unavailable",
                "reason": f"provider pin unavailable: {type(exc).__name__}",
                "gui_launch_counts_as_inference": False,
                "effect_allowed": False,
            })
    lanes.append(probe_antigravity(antigravity_observation, gui_paths=gui_paths))
    return {
        "admitted": False,
        "inference_executed": False,
        "reason": "catalog only; admission requires owner, run_id, work_item_id, operation_id, grant_id and agent_id",
        "lanes": lanes,
    }


def shell_fleet_notice(catalog: Mapping[str, Any] | None = None) -> str:
    view = catalog or describe_local_fleet()
    lanes = list(view.get("lanes") or [])
    parts = []
    antigravity = "indisponível"
    antigravity_reason = "contrato de inferência não interativa ausente"
    for lane in lanes:
        if not isinstance(lane, dict):
            continue
        if lane.get("id") == "antigravity":
            antigravity = str(lane.get("availability") or "unavailable")
            antigravity_reason = str(lane.get("reason") or antigravity_reason)
            continue
        state = "presente" if lane.get("installed") else "ausente"
        parts.append(f"{lane.get('id')}={state}/{lane.get('availability')}")
    roster = ", ".join(parts) if parts else "sem faixas"
    return (
        "ADMISSÃO DA FROTA (catálogo local, sem inferência nesta leitura): "
        + roster
        + f". antigravity={antigravity}: {antigravity_reason}. "
        "Executável presente não autentica e não admite. "
        "A admissão única exige owner, run_id, work_item_id, operation_id, grant_id e agent_id. "
        "Operação UNCERTAIN não é reenviada. Janela gráfica não é inferência."
    )


def _lane_override(observations: Mapping[str, Any] | None, lane_id: str) -> Mapping[str, Any]:
    if not isinstance(observations, Mapping):
        return {}
    lanes = observations.get("lanes")
    if not isinstance(lanes, Mapping):
        return {}
    raw = lanes.get(lane_id)
    return raw if isinstance(raw, Mapping) else {}


def admit_fleet(authority: Mapping[str, Any], observations: Mapping[str, Any] | None = None, *,
                root: Path | None = None, gui_paths: tuple[Path, ...] | None = None) -> dict[str, Any]:
    bound = _authority(authority)
    anti_observation = None
    if isinstance(observations, Mapping):
        raw_anti = observations.get("antigravity")
        if isinstance(raw_anti, Mapping):
            anti_observation = raw_anti.get("noninteractive") if "noninteractive" in raw_anti else raw_anti
            if anti_observation is not None and not isinstance(anti_observation, Mapping):
                anti_observation = None
    catalog = describe_local_fleet(root, antigravity_observation=anti_observation, gui_paths=gui_paths)
    lanes = []
    for lane in catalog["lanes"]:
        current = dict(lane)
        override = _lane_override(observations, str(current["id"]))
        delivery = str(override.get("delivery_state") or "").upper()
        operation_id = override.get("operation_id")
        if delivery == "UNCERTAIN" or override.get("execution_uncertain") is True:
            current["delivery_state"] = "UNCERTAIN"
            current["effect_allowed"] = False
            current["availability"] = "unavailable"
            current["reason"] = "UNCERTAIN operation is not resent"
            if isinstance(operation_id, str) and operation_id.strip():
                note_uncertain_effect(operation_id.strip())
                current["operation_id"] = operation_id.strip()
        elif current["id"] == "antigravity" and current.get("inference_verified") is not True:
            current["effect_allowed"] = False
        lanes.append(current)
    digest = hashlib.sha256(json.dumps(
        {"authority": bound, "lanes": [lane["id"] for lane in lanes]},
        sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    return {
        "admitted": True,
        "admission_id": digest,
        "authority": bound,
        "inference_executed": False,
        "physical_inference": False,
        "lanes": lanes,
        "reason": "single fleet admission; inference is not claimed",
    }


def lane_effect_allowed(admission: Mapping[str, Any], lane_id: str) -> dict[str, Any]:
    if not isinstance(admission, Mapping) or admission.get("admitted") is not True:
        raise FleetAdmissionError("fleet effect requires the single admission")
    token = _token(lane_id, "lane_id")
    for lane in admission.get("lanes") or []:
        if isinstance(lane, dict) and lane.get("id") == token:
            if lane.get("delivery_state") == "UNCERTAIN" or lane.get("effect_allowed") is not True:
                raise FleetAdmissionError(str(lane.get("reason") or "lane effect is not allowed"))
            operation_id = lane.get("operation_id")
            if isinstance(operation_id, str):
                claim_effect(operation_id)
            return dict(lane)
    raise FleetAdmissionError("lane is outside the fleet admission")


FROZEN_NO_RESEND = frozenset({"op-94baad8161fb6fd4b4423e6ac1aecdeb"})


def prepare_live_trio(*, placement: str = "host", guest_process: Mapping[str, Any] | None = None,
                      operation_id: str | None = None) -> dict[str, Any]:
    """Read CLI auth and guest prerequisites. Does not send a prompt or start a VM."""
    import subprocess
    placed = place_execution(placement, guest_process)
    if isinstance(operation_id, str) and operation_id in FROZEN_NO_RESEND:
        note_uncertain_effect(operation_id)
        raise FleetAdmissionError("UNCERTAIN operation is not resent")
    codex = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe"
    opencode = Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules" / "@opencode" / "cli" / "bin" / "opencode.exe"
    prerequisites: list[str] = []
    codex_login = False
    if not _file_exists(codex):
        prerequisites.append("codex executable")
    else:
        try:
            result = subprocess.run(
                [str(codex), "login", "status"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=8, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            text = (result.stderr or result.stdout).decode("utf-8", "replace")
            codex_login = result.returncode == 0 and "Logged in" in text
        except (OSError, subprocess.TimeoutExpired):
            codex_login = False
        if not codex_login:
            prerequisites.append("codex login")
    opencode_authenticated = False
    if not _file_exists(opencode):
        prerequisites.append("opencode executable")
    else:
        try:
            result = subprocess.run(
                [str(opencode), "auth", "list", "--standalone"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            text = result.stdout.decode("utf-8", "replace")
            opencode_authenticated = result.returncode == 0 and "No authenticated integrations" not in text and bool(text.strip())
        except (OSError, subprocess.TimeoutExpired):
            opencode_authenticated = False
        if not opencode_authenticated:
            prerequisites.append("opencode authenticated integration")
    return {
        "ready": not prerequisites and placement == "host",
        "prerequisites": prerequisites,
        "codex_login": codex_login,
        "opencode_authenticated": opencode_authenticated,
        "placement": placed,
        "physical_inference": False,
        "executed": False,
        "vboxmanage_used": False,
    }


PINNED_MUSE = "opencode/muse-spark-1.3-contributor-free"
_MODELS_DEV_CATALOG_KEY = "models-dev:catalog"


def _opencode_data_dir() -> Path:
    override = os.environ.get("XDG_DATA_HOME", "").strip()
    root = Path(override) if override else Path.home() / ".local" / "share"
    return root / "opencode"


def _stored_secret(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value.strip() != "public"


def _opencode_credential_stored() -> bool:
    """A stored OpenCode credential is not invented and is not another provider."""
    if _stored_secret(os.environ.get("OPENCODE_API_KEY")):
        return True
    path = _opencode_data_dir() / "auth.json"
    if not _file_exists(path):
        return False
    try:
        raw = path.read_bytes()
    except OSError:
        return False
    if not raw.strip():
        return False
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(parsed, dict):
        return False
    entry = parsed.get("opencode")
    if isinstance(entry, str):
        return _stored_secret(entry)
    if not isinstance(entry, dict):
        return False
    return _stored_secret(entry.get("key")) or _stored_secret(entry.get("apiKey"))


def _catalog_document(raw: bytes) -> bytes:
    """Return the stored catalog document. Empty, missing, or blank is zero bytes."""
    if not raw.strip():
        return b""
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return b""
    if isinstance(parsed, dict) and isinstance(parsed.get("body"), str):
        body = parsed["body"]
        if not body.strip() or body.strip() in {"{}", "[]", "null"}:
            return b""
        return body.encode("utf-8")
    if isinstance(parsed, dict) and isinstance(parsed.get("body"), (dict, list)):
        if not parsed["body"]:
            return b""
        return raw
    if isinstance(parsed, (dict, list)) and not parsed:
        return b""
    return raw


def _read_models_dev_catalog() -> bytes:
    """Read the local models.dev snapshot. This does not fetch and does not fill a missing file."""
    database = _opencode_data_dir() / "opencode.db"
    if not _file_exists(database):
        return b""
    import sqlite3
    try:
        uri = "file:" + database.resolve().as_posix() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
    except (OSError, sqlite3.Error):
        return b""
    try:
        row = connection.execute(
            "SELECT value FROM kv WHERE key = ?",
            (_MODELS_DEV_CATALOG_KEY,),
        ).fetchone()
    except sqlite3.Error:
        return b""
    finally:
        connection.close()
    if not row or not isinstance(row[0], (str, bytes)):
        return b""
    raw = row[0].encode("utf-8") if isinstance(row[0], str) else row[0]
    return _catalog_document(raw)


def _document_lists_pinned_muse(document: bytes) -> bool:
    provider_id, separator, model_id = PINNED_MUSE.partition("/")
    if not separator or not provider_id or not model_id:
        return False
    try:
        parsed = json.loads(document.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(parsed, dict):
        return False
    provider = parsed.get(provider_id)
    models = provider.get("models") if isinstance(provider, dict) else None
    model = models.get(model_id) if isinstance(models, dict) else None
    if not isinstance(model, dict):
        return False
    return model.get("status") != "deprecated"


def installed_muse_catalog() -> dict[str, Any]:
    """Read the local OpenCode catalog. This does not send a prompt, call the network, or declare a login.

    An empty or missing catalog does not make Muse available. Without a stored OpenCode
    credential, the public snapshot is not an installed listing and contributes no bytes.
    """
    executable = Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules" / "@opencode" / "cli" / "bin" / "opencode.exe"
    installed = _file_exists(executable)
    document = _read_models_dev_catalog()
    if not document or not _opencode_credential_stored():
        return {"listed": False, "catalog_bytes": 0, "inference": False, "executable": installed}
    return {
        "listed": _document_lists_pinned_muse(document),
        "catalog_bytes": len(document),
        "inference": False,
        "executable": installed,
    }


LIVE_LANES = frozenset({"sentra-cli", "opencode", "codex"})


def canonical_lane(tool: Any) -> str:
    name = str(tool or "").strip().lower().replace("_", "-")
    if name in {"antigravity", "antigravity-app"}:
        raise FleetAdmissionError(
            "Antigravity graphical application is not a verified non-interactive inference"
        )
    if name not in LIVE_LANES:
        raise FleetAdmissionError("lane is outside the fleet admission")
    return name


def refuse_blocked_dispatch(*, tool: Any, placement: str = "host",
                            guest_process: Mapping[str, Any] | None = None,
                            operation_ids: tuple[Any, ...] | list[Any] = ()) -> dict[str, Any]:
    """Hard refusals shared by the live dispatch. This does not start a process."""
    lane = canonical_lane(tool)
    for operation_id in operation_ids:
        if not isinstance(operation_id, str) or not operation_id:
            continue
        if operation_id in FROZEN_NO_RESEND or operation_id in _UNCERTAIN:
            note_uncertain_effect(operation_id)
            raise FleetAdmissionError("UNCERTAIN operation is not resent")
    placed = place_execution(placement, guest_process)
    placed["lane"] = lane
    return placed


def bind_live_lane(*, tool: Any, authority: Mapping[str, Any], placement: str = "host",
                   guest_process: Mapping[str, Any] | None = None,
                   effect_operation_id: str | None = None, effect_state: str | None = None,
                   require_installed: bool = True) -> dict[str, Any]:
    """Admit one CLI lane on the live dispatch path before any runner starts."""
    placed = refuse_blocked_dispatch(
        tool=tool, placement=placement, guest_process=guest_process,
        operation_ids=(authority.get("operation_id") if isinstance(authority, Mapping) else None,
                       effect_operation_id),
    )
    if str(effect_state or "").upper() == "UNCERTAIN":
        if isinstance(effect_operation_id, str) and effect_operation_id:
            note_uncertain_effect(effect_operation_id)
        raise FleetAdmissionError("UNCERTAIN operation is not resent")
    if isinstance(effect_operation_id, str) and effect_operation_id:
        claim_effect(effect_operation_id)
    admitted = admit_fleet(authority)
    if require_installed:
        lane_effect_allowed(admitted, placed["lane"])
    return {
        "admission_id": admitted["admission_id"],
        "placement": placed,
        "lane": placed["lane"],
        "physical_inference": False,
        "inference_executed": False,
    }


def guard_recorded_outcome(*, tool: Any, operation_id: str, operation_state: str,
                           receipt: Mapping[str, Any] | None = None,
                           placement: str = "host",
                           guest_process: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Refuse to close a recorded dispatch that is uncertain, graphical, or unverified in the guest."""
    if isinstance(receipt, Mapping) and receipt.get("placement") == "guest" and placement == "host":
        placement = "guest"
        guest_process = receipt.get("guest_process") if isinstance(receipt.get("guest_process"), Mapping) else guest_process
    placed = refuse_blocked_dispatch(
        tool=tool, placement=placement, guest_process=guest_process,
        operation_ids=(operation_id,),
    )
    state = str(operation_state or "").upper()
    uncertain = state == "UNCERTAIN"
    if isinstance(receipt, Mapping) and (
        receipt.get("execution_uncertain") is True or receipt.get("status") == "UNCERTAIN"
    ):
        uncertain = True
    if uncertain:
        note_uncertain_effect(operation_id)
        raise FleetAdmissionError("UNCERTAIN operation is not resent")
    return placed


def _dot_vm_registry_id(guest_process: Mapping[str, Any] | None) -> str | None:
    """A Dot VM row is a placement witness. It is not a running guest process."""
    if not isinstance(guest_process, Mapping) or guest_process.get("vm_registry_bound") is not True:
        return None
    if guest_process.get("verified") is True:
        return None
    from sentra_executors.guest_execution import safe_vm_id
    return safe_vm_id(guest_process.get("vm_id"))


def place_execution(placement: str, guest_process: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if placement == "host":
        return {"placement": "host", "guest_process_verified": False, "claims_guest_execution": False}
    if placement != "guest":
        raise ValueError("placement must be host or guest")
    vm_id = _dot_vm_registry_id(guest_process)
    if vm_id is not None:
        return {
            "placement": "guest",
            "guest_process_verified": False,
            "claims_guest_execution": False,
            "vm_registry_bound": True,
            "vm_id": vm_id,
        }
    if not isinstance(guest_process, Mapping) or guest_process.get("verified") is not True:
        raise FleetAdmissionError("guest execution requires a verified guest process")
    pid = guest_process.get("pid")
    if type(pid) is not int or pid <= 0:
        raise FleetAdmissionError("guest execution requires a verified guest process")
    evidence = guest_process.get("evidence_sha256")
    if not _sha256(evidence):
        raise FleetAdmissionError("guest execution requires a verified guest process")
    raise FleetAdmissionError("a process id is not a guest execution")
