from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="server.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--name")
    parser.add_argument("--version")
    parser.add_argument("--remote-url")
    parser.add_argument("--repository-url")
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if args.name:
        data["name"] = args.name
    if args.version:
        data["version"] = args.version
    if args.remote_url:
        data["remotes"] = [{"type": "streamable-http", "url": args.remote_url}]
    if args.repository_url:
        data["repository"] = {"url": args.repository_url, "source": "github"}
    Path(args.output).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
