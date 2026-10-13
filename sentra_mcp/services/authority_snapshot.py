"""Encrypted authority files and OS-key prerequisites for offline recovery.

The archive holds ciphertext, not a pointer to its contents in a keyring. An
optional host-supplied recovery key wraps the archive key. Existing DPAPI-bound
domain bytes retain their identity/hash and therefore require their OS profile.
"""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import tempfile

from sentra_remote.secrets import protect_secret, unprotect_secret


CHUNK_BYTES = 384 * 1024


class SnapshotCodec:
    def __init__(self, directory, *, recovery_key=None, create=False):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:
            raise RuntimeError("encrypted native backup requires optional cryptography AESGCM") from exc
        if recovery_key is not None and (not isinstance(recovery_key, bytes) or len(recovery_key) != 32):
            raise ValueError("host recovery key must be 32 bytes from a protected key source")
        self.aead, self.root = AESGCM, Path(directory).resolve()
        header_path = self.root / "archive-key.json"
        if create:
            key = secrets.token_bytes(32)
            self.header = {"version": 1, "archive_id": secrets.token_hex(24),
                           "os_wrapped_key": protect_secret(base64.b64encode(key).decode())}
            if recovery_key is not None:
                nonce = secrets.token_bytes(12)
                wrapped = AESGCM(recovery_key).encrypt(nonce, key, self.header["archive_id"].encode())
                self.header["recovery_wrapped_key"] = base64.b64encode(nonce + wrapped).decode()
            header_path.write_text(json.dumps(self.header, sort_keys=True), encoding="utf-8")
        else:
            self.header = json.loads(header_path.read_text(encoding="utf-8"))
            if self.header.get("version") != 1:
                raise ValueError("unsupported encrypted archive version")
            if recovery_key is not None:
                raw = base64.b64decode(self.header["recovery_wrapped_key"], validate=True)
                key = AESGCM(recovery_key).decrypt(raw[:12], raw[12:], self.header["archive_id"].encode())
            else:
                key = base64.b64decode(unprotect_secret(self.header["os_wrapped_key"]), validate=True)
        self.key = key

    def encode(self, value, label):
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        nonce = secrets.token_bytes(12)
        aad = (self.header["archive_id"] + "\0" + label).encode()
        return nonce + self.aead(self.key).encrypt(nonce, raw, aad)

    def decode(self, raw, label):
        aad = (self.header["archive_id"] + "\0" + label).encode()
        return json.loads(self.aead(self.key).decrypt(raw[:12], raw[12:], aad))


def collect_keys(value, entries):
    """Capture referenced keyring values and prove DPAPI keys are available."""
    if isinstance(value, dict):
        for name,child in value.items():
            if name not in {"content","text","instructions","objective","description","prompt","response","name","title","message"}:
                collect_keys(child, entries)
    elif isinstance(value, (tuple, list)):
        for child in value:
            collect_keys(child, entries)
    elif isinstance(value, (bytes, memoryview)):
        try:
            collect_keys(bytes(value).decode("utf-8"), entries)
        except UnicodeDecodeError:
            pass
    elif isinstance(value, str):
        if re.fullmatch(r"(?:dpapi:[A-Za-z0-9+/=]+|keyring:[A-Za-z0-9_-]+)",value):
            if value not in entries:
                plain = unprotect_secret(value)
                entries[value] = plain
                # Only structured persisted containers are inspected; prose is data.
                try:
                    nested = json.loads(plain)
                except (ValueError,TypeError):
                    return
                if isinstance(nested,(dict,list)):
                    collect_keys(nested,entries)
        elif value.startswith(("{","[")):
            try:
                nested = json.loads(value)
            except (ValueError,TypeError):
                return
            if isinstance(nested,(dict,list)):
                collect_keys(nested,entries)


def restore_keys(entries):
    # Preflight DPAPI before changing keyring: never claim cross-profile restore.
    for reference, plain in entries.items():
        if reference.startswith("dpapi:") and unprotect_secret(reference) != plain:
            raise PermissionError("original DPAPI profile/key material required for archive recovery")
    for reference, plain in entries.items():
        if reference.startswith("keyring:"):
            import keyring
            previous = keyring.get_password("SENTRA Commander", reference[8:])
            if previous is not None and previous != plain:
                raise PermissionError("recovery keyring reference conflicts with current secret")
    for reference, plain in entries.items():
        if reference.startswith("keyring:"):
            import keyring
            keyring.set_password("SENTRA Commander", reference[8:], plain)


def _roots(roots):
    result = {}
    for label, path in roots.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", label):
            raise ValueError("invalid trusted archive root label")
        raw = Path(path).absolute()
        if raw.is_symlink() or getattr(raw,"is_junction",lambda:False)():
            raise PermissionError("archive root cannot be a link/junction")
        result[label] = raw.resolve()
    values = list(result.values())
    if any(a == b or a.is_relative_to(b) or b.is_relative_to(a) for i,a in enumerate(values) for b in values[i+1:]):
        raise ValueError("archive roots overlap")
    return result


def _files(root, excluded):
    for directory, children, files in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in list(children):
            child = base / name
            if any(child.resolve().is_relative_to(p) for p in excluded):
                children.remove(name)
            elif child.is_symlink() or getattr(child,"is_junction",lambda:False)():
                raise PermissionError("authority archive cannot traverse links/junctions")
        for name in sorted(files):
            yield base / name


def _stream_keys(stream, keys):
    while True:
        raw = stream.readline(4_030_001)
        if not raw:
            break
        if len(raw) > 4_030_000:
            if raw.startswith((b"dpapi:",b"keyring:")):
                raise ValueError("OS protected token exceeds archive recovery bound")
            while raw and not raw.endswith(b"\n"):
                raw = stream.readline(4_030_001)
            continue
        stripped = raw.strip()
        if stripped.startswith((b"dpapi:",b"keyring:")):
            collect_keys(stripped,keys)
        elif stripped.startswith((b"{",b"[")):
            try:
                value = json.loads(stripped)
            except (ValueError,UnicodeDecodeError):
                continue  # Opaque artifact bytes are still archived verbatim.
            collect_keys(value,keys)
    stream.seek(0)


def capture_files(codec, roots, keys, *, excluded=()):
    roots = _roots(roots)
    excluded = [Path(path).resolve() for path in excluded] + [codec.root]
    files = []
    for label, root in roots.items():
        if not root.exists():
            continue
        for path in _files(root,excluded):
            if any(path.resolve().is_relative_to(p) for p in excluded):
                continue
            if path.is_symlink() or getattr(path,"is_junction",lambda:False)():
                raise PermissionError("authority archive cannot follow links/junctions")
            if path.is_dir() or path.name == "authority-recovery.json" or path.name.startswith(".authority-restore-") or path.name.endswith(("-wal", "-shm", ".lock")):
                continue
            if not path.is_file():
                raise PermissionError("authority archive contains a special file")
            before = path.stat()
            chunks, digest, size = [], hashlib.sha256(), 0
            # Sidecar SQLite stores are captured with their WAL transaction.
            with path.open("rb") as probe:
                is_sqlite = probe.read(16) == b"SQLite format 3\0"
            if is_sqlite:
                with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as source, sqlite3.connect(":memory:") as dest:
                    source.backup(dest)
                    for (table,) in dest.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
                        quoted = '"' + table.replace('"','""') + '"'
                        for row in dest.execute("SELECT * FROM " + quoted):
                            collect_keys(row, keys)
                    snapshot_bytes = dest.serialize()
                stream_context = io.BytesIO(snapshot_bytes)
            else:
                stream_context = path.open("rb")
            with stream_context as stream:
                if not is_sqlite:
                    _stream_keys(stream,keys)
                while True:
                    raw = stream.read(CHUNK_BYTES)
                    if not raw:
                        break
                    digest.update(raw); size += len(raw)
                    filename = "file-" + str(len(files)) + "-" + str(len(chunks)) + ".sealed"
                    encrypted = codec.encode({"bytes": base64.b64encode(raw).decode()}, filename)
                    (codec.root / filename).write_bytes(encrypted)
                    chunks.append({"file": filename, "sha256": hashlib.sha256(encrypted).hexdigest()})
            after = path.stat()
            if (before.st_size,before.st_mtime_ns) != (after.st_size,after.st_mtime_ns):
                raise RuntimeError("authority files changed during quiesced backup")
            files.append({"root": label, "path": path.relative_to(root).as_posix(), "bytes": size,
                          "sha256": digest.hexdigest(), "chunks": chunks, "sqlite_snapshot": is_sqlite})
    return {"roots": {name:str(path) for name,path in roots.items()}, "files": files,
            "dpapi_original_profile_required": any(ref.startswith("dpapi:") for ref in keys)}


def stage_files(codec, snapshot, roots):
    roots = _roots(roots)
    if set(roots) != set(snapshot["roots"]):
        raise ValueError("restore requires every original trusted root mapping")
    staged = []
    try:
        for item in snapshot["files"]:
            relative = Path(item["path"])
            if relative.is_absolute() or ".." in relative.parts or ":" in item["path"] or "\\" in item["path"]:
                raise PermissionError("invalid authority file path")
            root = roots[item["root"]]
            target = root / relative
            if not target.resolve().is_relative_to(root):
                raise PermissionError("restore target outside trusted root")
            for parent in [target, *target.parents]:
                if parent == root.parent:
                    break
                if parent.is_symlink() or getattr(parent,"is_junction",lambda:False)():
                    raise PermissionError("restore target traverses link/junction")
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, filename = tempfile.mkstemp(prefix=".authority-restore-", dir=target.parent)
            temporary = Path(filename)
            staged.append((temporary,target))
            digest, size = hashlib.sha256(), 0
            with os.fdopen(fd,"wb") as stream:
                for chunk in item["chunks"]:
                    name = chunk["file"]
                    if Path(name).name != name:
                        raise PermissionError("invalid encrypted file chunk")
                    encrypted = (codec.root / name).read_bytes()
                    if hashlib.sha256(encrypted).hexdigest() != chunk["sha256"]:
                        raise ValueError("authority file chunk digest mismatch")
                    raw = base64.b64decode(codec.decode(encrypted,name)["bytes"],validate=True)
                    stream.write(raw); digest.update(raw); size += len(raw)
                stream.flush(); os.fsync(stream.fileno())
            if digest.hexdigest() != item["sha256"] or size != item["bytes"]:
                raise ValueError("authority file integrity mismatch")
        return staged
    except BaseException:
        for temporary,_ in staged:
            temporary.unlink(missing_ok=True)
        raise


def publish_files(staged):
    for temporary,target in staged:
        temporary.replace(target)
