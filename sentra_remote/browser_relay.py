"""Standalone loopback Edge relay for installed SENTRA Desktop."""
from __future__ import annotations

import argparse
import signal
import threading
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from native_bridge.relay import RelayServer
    from sentra_mcp.services.control_plane import ControlPlaneService

from .product import ProductPaths, ensure_browser_token


def create_relay(*, state_dir: Path, extension_dir: Path, host: str = "127.0.0.1",
                 port: int = 8765, control: ControlPlaneService | None = None) -> RelayServer:
    """Compose the installed relay with the existing central SQLite authority.

    An embedded host can pass its ControlPlane instance. The standalone process
    opens the same state root, never a detached BrowserEvidence database.
    Construction does not enroll a collector, grant permission or dispatch jobs.
    """
    from native_bridge.relay import RelayServer
    from sentra_mcp.services.context import ContextBusService
    from sentra_mcp.services.control_plane import ControlPlaneService
    from sentra_mcp.services.durable import DurableRunService
    state_dir = Path(state_dir).expanduser().resolve()
    extension_dir = Path(extension_dir).expanduser().resolve()
    if not extension_dir.is_dir():
        raise FileNotFoundError(f"Edge extension directory is missing: {extension_dir}")
    if control is None:
        control = ControlPlaneService(DurableRunService(state_dir), ContextBusService(state_dir))
    elif Path(control.durable.state_root).resolve() != state_dir:
        raise ValueError("relay and Control Plane must use the same state directory")
    paths = ProductPaths(extension_dir.parent, state_dir)
    database = paths.browser_dir / "relay.sqlite3"
    database.parent.mkdir(parents=True, exist_ok=True)
    return RelayServer(host=host, port=port, extension_dir=extension_dir,
                       token=ensure_browser_token(paths), db_path=database,
                       authenticated_control=control)


def main(argv: list[str] | None = None) -> int:
    import sys
    from .enrollment_native import is_native_invocation, run_native
    native_args = list(sys.argv[1:] if argv is None else argv)
    if is_native_invocation(native_args):
        return run_native(native_args)
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
    relay = create_relay(state_dir=state_dir, extension_dir=extension_dir,
                         host=args.host, port=args.port).start()
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
