"""CLI for the hosted SENTRA Relay."""
from __future__ import annotations

import argparse
from pathlib import Path

from .relay import RemoteRelayServer
from .store import RemoteStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sentra-relay")
    parser.add_argument("--store", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--tls-cert")
    parser.add_argument("--tls-key")
    args = parser.parse_args(argv)
    store = RemoteStore(Path(args.store))
    server = RemoteRelayServer(
        store,
        host=args.host,
        port=args.port,
        tls_cert=args.tls_cert,
        tls_key=args.tls_key,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
