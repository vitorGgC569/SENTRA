"""Two whole-file unit partitions with independently checked exact coverage.

Both runners collect the complete recursive suite. Nothing is selected from a
historical allowlist: new files participate immediately. The required coverage
job compares their full collections, planned partitions and actually attempted
tests, and rejects missing/duplicate cases or incomplete/failed executions.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys

PARTITIONS = 2
ROOT = Path(__file__).resolve().parents[2]


def file_of(node_id: str) -> str:
    if not isinstance(node_id, str) or not node_id:
        raise ValueError("invalid collected test identity")
    name = node_id.split("::", 1)[0]
    path = PurePosixPath(name)
    if ("\\" in name or path.is_absolute() or ".." in path.parts
            or not name.startswith("tests/unit/") or path.suffix != ".py"
            or str(path) != name):
        raise ValueError("test is outside the recursive unit suite: " + name)
    return name


def file_partition(name: str) -> int:
    return int.from_bytes(hashlib.sha256(name.encode("utf-8")).digest()[:8], "big") % PARTITIONS


def partition_nodes(nodes: list[str]) -> list[list[str]]:
    if not nodes or len(nodes) != len(set(nodes)):
        raise ValueError("empty or duplicate full collection")
    parts: list[list[str]] = [[], []]
    for node in sorted(nodes):
        parts[file_partition(file_of(node))].append(node)
    if any(not part for part in parts):
        raise ValueError("unit partition is empty")
    validate_coverage(nodes, parts)
    return parts


def validate_coverage(nodes: list[str], parts: list[list[str]]) -> None:
    if len(parts) != PARTITIONS or not nodes or len(set(nodes)) != len(nodes):
        raise ValueError("invalid full collection or partition count")
    covered = [node for part in parts for node in part]
    if Counter(covered) != Counter(nodes):
        raise ValueError("partition coverage has omissions, duplicates or extra tests")
    for index, part in enumerate(parts):
        if not part or any(file_partition(file_of(node)) != index for node in part):
            raise ValueError("partition splits a file or violates deterministic assignment")


def collection_hash(nodes: list[str]) -> str:
    return hashlib.sha256(json.dumps(sorted(nodes), ensure_ascii=True,
                                    separators=(",", ":")).encode()).hexdigest()


def verify_manifests(manifests: list[dict], *, expected_revision: str | None = None) -> dict:
    if len(manifests) != PARTITIONS:
        raise ValueError("both unit partition manifests are required")
    by_index = {}
    for manifest in manifests:
        index = manifest.get("partition")
        if type(index) is not int or index not in range(PARTITIONS) or index in by_index:
            raise ValueError("missing or duplicate partition identity")
        if (manifest.get("schema") != 1 or manifest.get("partition_count") != PARTITIONS
                or manifest.get("mode") != "run" or manifest.get("exit_code") != 0):
            raise ValueError("unit partition did not successfully execute")
        by_index[index] = manifest
    first = by_index[0]
    full = first["full_collection"]
    planned = partition_nodes(full)
    revision = first.get("revision")
    if not isinstance(revision, str) or not revision:
        raise ValueError("source revision missing")
    if expected_revision is not None and revision != expected_revision:
        raise ValueError("unit manifests are for a different source revision")
    for index in range(PARTITIONS):
        manifest = by_index[index]
        if (manifest.get("revision") != revision or manifest.get("full_collection") != full
                or manifest.get("collection_sha256") != collection_hash(full)):
            raise ValueError("unit partitions disagree about source or full collection")
        if manifest.get("selected") != planned[index]:
            raise ValueError("selected tests differ from the complete deterministic plan")
        if Counter(manifest.get("attempted", [])) != Counter(planned[index]):
            raise ValueError("unit execution omitted or duplicated selected tests")
    validate_coverage(full, [by_index[i]["selected"] for i in range(PARTITIONS)])
    return {"verified": True, "revision": revision, "tests": len(full),
            "files": len({file_of(node) for node in full}),
            "collection_sha256": collection_hash(full),
            "partition_tests": [len(part) for part in planned]}


def run_partition(index: int, output: Path, revision: str, *, collect_only=False) -> int:
    import pytest

    if os.environ.get("PYTEST_ADDOPTS", "").strip():
        raise ValueError("PYTEST_ADDOPTS must not filter the required unit collection")
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    manifest = {"schema": 1, "partition_count": PARTITIONS, "partition": index,
                "revision": revision, "mode": "collect" if collect_only else "run",
                "attempted": [], "exit_code": None}

    class PartitionPlugin:
        own_deselection = False
        external_deselection = False

        def pytest_deselected(self, items):
            if items and not self.own_deselection:
                self.external_deselection = True

        @pytest.hookimpl(trylast=True)
        def pytest_collection_modifyitems(self, session, config, items):
            if self.external_deselection or config.option.keyword or config.option.markexpr:
                raise pytest.UsageError("filtering required unit collection is forbidden")
            nodes = sorted(item.nodeid for item in items)
            parts = partition_nodes(nodes)
            manifest.update(full_collection=nodes, collection_sha256=collection_hash(nodes),
                            selected=parts[index])
            if not collect_only:
                selected = set(parts[index])
                others = [item for item in items if item.nodeid not in selected]
                items[:] = [item for item in items if item.nodeid in selected]
                self.own_deselection = True
                try:
                    config.hook.pytest_deselected(items=others)
                finally:
                    self.own_deselection = False

        def pytest_collection_finish(self, session):
            expected = manifest.get("full_collection" if collect_only else "selected")
            if self.external_deselection or sorted(item.nodeid for item in session.items) != expected:
                raise pytest.UsageError("unit collection was changed outside its partition plan")

        def pytest_runtest_logreport(self, report):
            if report.when == "setup":
                manifest["attempted"].append(report.nodeid)

    args = ["-q", "tests/unit", "--rootdir", str(ROOT), "-o", "faulthandler_timeout=120"]
    if collect_only:
        args += ["--collect-only"]
    else:
        args += ["--junitxml=test-results.xml"]
    output.parent.mkdir(parents=True, exist_ok=True)
    exit_code = int(pytest.main(args, plugins=[PartitionPlugin()]))
    manifest["exit_code"] = exit_code
    if exit_code == 0 and not collect_only:
        if Counter(manifest["attempted"]) != Counter(manifest.get("selected", [])):
            manifest["exit_code"] = exit_code = 1
    output.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return exit_code


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--partition", type=int, choices=range(PARTITIONS))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--revision", default="local")
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--verify", nargs="+", type=Path)
    parser.add_argument("--expected-revision")
    options = parser.parse_args(argv)
    if options.verify:
        if options.partition is not None or options.output or options.collect_only:
            parser.error("verification cannot execute tests")
        print(json.dumps(verify_manifests([json.loads(path.read_text(encoding="utf-8"))
                                          for path in options.verify],
                                         expected_revision=options.expected_revision), sort_keys=True))
        return 0
    if options.expected_revision:
        parser.error("--expected-revision requires --verify")
    if options.partition is None or options.output is None:
        parser.error("--partition and --output are required")
    return run_partition(options.partition, options.output, options.revision,
                         collect_only=options.collect_only)


if __name__ == "__main__":
    raise SystemExit(main())
