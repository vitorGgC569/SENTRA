"""Relocate only typed host paths during an offline authority migration."""
import hashlib
import json
from pathlib import Path
from sentra_core.conversations import _encode, _decode


PATH_FIELDS = frozenset({"executable","workspace_root","npm_cli","entrypoint",
    "archive_path","installed_path","journal_path","state_root","database"})


def relocate_path(value, source_root, target_root):
    if not isinstance(value,str) or not Path(value).is_absolute():
        return value
    path,source = Path(value).resolve(),Path(source_root).resolve()
    return str(Path(target_root).resolve() / path.relative_to(source)) if path.is_relative_to(source) else value


def relocate_machine_configuration(row, source_root, target_root):
    result = dict(row)
    config = _decode(row["config"]) if row["config"].startswith(("dpapi:","keyring:")) else json.loads(row["config"])
    def visit(value):
        if isinstance(value,dict):
            out = {}
            for key,child in value.items():
                if key in PATH_FIELDS:
                    out[key] = relocate_path(child,source_root,target_root)
                elif key == "args" and isinstance(child,list):
                    out[key] = [relocate_path(arg,source_root,target_root) for arg in child]
                elif key == "argument_file_pins" and isinstance(child,dict):
                    out[key] = {relocate_path(path,source_root,target_root):pin for path,pin in child.items()}
                else:
                    out[key] = visit(child)
            return out
        if isinstance(value,list):
            return [visit(child) for child in value]
        return value  # Instructions/prose, identifiers and secrets are never path inputs.
    config = visit(config)
    canonical = json.dumps(config,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(",",":"))
    result["config"],result["sha256"] = _encode(config),hashlib.sha256(canonical.encode()).hexdigest()
    return result
