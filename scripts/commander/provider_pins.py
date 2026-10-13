"""Optional-provider pins / SBOM / NOTICE inventory (Vitra-owned, read-only).

Reports the transitive per-file pin table consumed by release composition.
Never downloads, installs or modifies anything.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA = 1


def inventory() -> dict:
    from sentra_remote.optional_providers import transitive_inventory
    return {"schema": SCHEMA, **transitive_inventory()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only provider pin/SBOM/NOTICE inventory")
    parser.parse_args(argv)
    print(json.dumps(inventory(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
