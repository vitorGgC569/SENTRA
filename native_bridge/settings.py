"""Local pairing secret. Never log its value or expose it to model context."""
import os
import secrets
from pathlib import Path


def relay_settings(root: Path):
    private = Path(root).resolve() / ".oma"
    if private.is_symlink() or (hasattr(private, "is_junction") and private.is_junction()):
        raise ValueError("relay storage cannot be a filesystem link")
    private.mkdir(exist_ok=True)
    path = private / "relay-token"
    database = private / "relay.sqlite3"
    if path.is_symlink() or database.is_symlink():
        raise ValueError("relay secret/database cannot be a link")
    if not path.exists():
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(secrets.token_urlsafe(32))
    token = os.environ.get("OMA_RELAY_TOKEN") or path.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise ValueError("invalid relay token; minimum 32 characters")
    return token, path, database
