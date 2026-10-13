"""Real pinned payload lifecycle and scoped registrations for optional runtimes."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import shutil
import time

from .lifecycle_effects import checkpoint_effect, provider_context
from sentra_core.conversations import _encode, _decode


@contextmanager
def registry(context):
    db = context["control"].store.connect("shell")
    try:
        with db:
            db.executescript("""CREATE TABLE IF NOT EXISTS optional_runtime_registrations(
                owner TEXT NOT NULL,installation_id TEXT NOT NULL,provider TEXT NOT NULL,
                revision INTEGER NOT NULL,state TEXT NOT NULL,protected_config TEXT NOT NULL,
                updated_at REAL NOT NULL,PRIMARY KEY(owner,installation_id,provider));""")
            yield db
    finally:
        db.close()


def registration(name, *, state, configuration):
    context = provider_context(); checkpoint_effect()
    with registry(context) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO optional_runtime_registrations VALUES(?,?,?,?,?,?,?) ON CONFLICT(owner,installation_id,provider) DO UPDATE SET revision=optional_runtime_registrations.revision+1,state=excluded.state,protected_config=excluded.protected_config,updated_at=excluded.updated_at",
            (context["owner"], context["installation_id"], name, 1, state, _encode(configuration), time.time()))
    return {"provider": name, "state": state, "ok": state in {"ready", "revoked", "removed"}}


def load_registration(name):
    context = provider_context()
    with registry(context) as db:
        row = db.execute("SELECT * FROM optional_runtime_registrations WHERE owner=? AND installation_id=? AND provider=?",
            (context["owner"], context["installation_id"], name)).fetchone()
    return {"state": row["state"], "config": _decode(row["protected_config"]), "revision": row["revision"]} if row else None


def _confined(root, relative):
    if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative:
        raise ValueError("managed payload requires portable relative path")
    path = Path(relative)
    if path.is_absolute() or any(p in {".", ".."} for p in path.parts):
        raise PermissionError("managed payload path escaped root")
    raw = Path(root).absolute()
    if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in (raw, *raw.parents)):
        raise PermissionError('linked managed payload root')
    base = raw.resolve(strict=True)
    target = base
    for part in path.parts:
        target /= part
        if target.is_symlink() or (hasattr(target, "is_junction") and target.is_junction()):
            raise PermissionError("linked managed payload path")
    if not target.resolve().is_relative_to(base):
        raise PermissionError("managed payload path escaped root")
    return target


def _sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def payload_runner(name, action):
    context = provider_context()
    spec = context.get("configuration") or {}
    if action == 'configure':
        if not isinstance(spec, dict) or not spec.get('version'):
            raise RuntimeError('host provider configuration with a release pin required')
        # Functions stay in the host registry. Credentials remain protected references.
        configuration = {k: v for k, v in spec.items() if not callable(v)}
        json.dumps(configuration, allow_nan=False)
        previous = load_registration(name)
        if previous and previous['state'] not in {'revoked', 'removed'}:
            configuration = {**previous['config'], 'settings': configuration}
        else:
            configuration = {'settings': configuration}
        result = registration(name, state='configured', configuration=configuration)
        return {**result, 'ok': True, 'ready': False}
    if action == "revoke":
        previous = load_registration(name)
        return registration(name, state="revoked", configuration=previous["config"] if previous else {})
    if action == "remove":
        previous = load_registration(name)
        if not previous:
            raise RuntimeError("owned provider registration required for removal")
        target_root = Path(previous["config"]["target_root"]).resolve(strict=True)
        expected_root = Path(context["state_root"]).resolve() / "providers" / name
        if target_root != expected_root:
            raise PermissionError("provider removal root binding changed")
        for item in previous["config"].get("files", []):
            target = _confined(target_root, item["path"])
            if target.exists():
                if _sha(target) != item["sha256"]:
                    raise FileExistsError("provider file changed; preserve it for review")
                checkpoint_effect(); target.unlink()
        return registration(name, state="removed", configuration={"files": []})
    if action in {"health", "renew", "recovery"}:
        previous = load_registration(name)
        if not previous or previous["state"] in {"revoked", "removed"}:
            return {"ok": False, "installed": False, "state": "absent"}
        config = previous["config"]
        if not config.get('target_root') or not config.get('files'):
            return {'ok': False, 'installed': False, 'state': 'configured'}
        root = Path(config["target_root"])
        for item in config["files"]:
            path = _confined(root, item["path"])
            if not path.is_file() or _sha(path) != item["sha256"]:
                return {"ok": False, "installed": True, "state": "degraded", "reason": "payload integrity changed"}
        probe = spec.get("health_probe")
        if not callable(probe):
            raise RuntimeError("optional runtime has no configured live health probe")
        checkpoint_effect(); observed = probe(root)
        if not isinstance(observed, dict):
            raise ValueError("provider health probe returned invalid evidence")
        state = "ready" if observed.get("ready") is True else "degraded"
        if action in {"renew", "recovery"}:
            registration(name, state=state, configuration=config)
        return {"ok": state == "ready", "installed": True, "state": state}
    if action not in {"install", "repair"}:
        raise ValueError("unknown pinned payload lifecycle action")
    files = spec.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= 20000 or not spec.get("version"):
        raise RuntimeError("pinned optional runtime source manifest is not configured")
    source = Path(spec["source_root"]).resolve(strict=True)
    target = Path(context["state_root"]).resolve() / "providers" / name
    if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in (target, *target.parents)):
        raise PermissionError("linked provider destination")
    checkpoint_effect(); target.mkdir(parents=True, exist_ok=True)
    planned, total, names = [], 0, set()
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get('path'), str):
            raise ValueError('invalid managed provider file entry')
        canonical = Path(item['path']).as_posix().casefold()
        if canonical in names:
            raise ValueError('duplicate provider path on Windows')
        names.add(canonical)
        digest = item.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("materialized provider manifest lacks exact file digest")
        original = _confined(source, item["path"])
        if not original.is_file() or _sha(original) != digest:
            raise PermissionError("provider source digest mismatch")
        total += original.stat().st_size
        if total > 4 * 1024 ** 3:
            raise ValueError("provider payload quota exceeded")
        planned.append((original, _confined(target, item["path"]), item))
    previous = load_registration(name)
    owned = {i["path"]:i["sha256"] for i in (previous or {}).get("config", {}).get("files", [])}
    for original, destination, item in planned:
        if destination.exists() and (_sha(destination) != owned.get(item["path"])):
            raise FileExistsError("refusing to replace unowned or modified provider file")
        checkpoint_effect(); destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".sentra-stage")
        if temporary.exists():
            raise FileExistsError("provider staging pending; reconcile before repair")
        checkpoint_effect()
        with original.open('rb') as incoming, temporary.open('xb') as outgoing:
            shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
            outgoing.flush()
            __import__('os').fsync(outgoing.fileno())
        if _sha(temporary) != item["sha256"]:
            raise RuntimeError("provider changed during copy")
        checkpoint_effect(); temporary.replace(destination)
    result = registration(name, state="degraded", configuration={"target_root": str(target), "version": spec["version"], "files": files})
    return {**result, "ok": True, "installed": True, "state": "installed", "files": len(files)}
