"""Standalone loopback Edge relay for installed SENTRA Desktop."""
from __future__ import annotations

import argparse
import signal
import threading
from pathlib import Path

from native_bridge.relay import RelayServer

from .product import ProductPaths, ensure_browser_token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sentra-browser-relay")
    parser.add_argument("--state-dir", default=str(Path.home() / ".sentra"))
    parser.add_argument("--extension-dir", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    args = parser.parse_args(argv)

    state_dir = Path(args.state_dir).expanduser().resolve()
    extension_dir = Path(args.extension_dir).expanduser().resolve()
    if not extension_dir.is_dir():
        raise FileNotFoundError(f"Edge extension directory is missing: {extension_dir}")
    paths = ProductPaths(extension_dir.parent, state_dir)
    token = ensure_browser_token(paths)
    database = paths.browser_dir / "relay.sqlite3"
    database.parent.mkdir(parents=True, exist_ok=True)
    relay = RelayServer(
        host=args.host,
        port=args.port,
        extension_dir=extension_dir,
        token=token,
        db_path=database,
    ).start()
    stopped = threading.Event()

    def stop(*_args) -> None:
        if not stopped.is_set():
            stopped.set()
            relay.stop()

    signal.signal(signal.SIGINT, stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop)
    try:
        stopped.wait()
    except KeyboardInterrupt:
        stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
