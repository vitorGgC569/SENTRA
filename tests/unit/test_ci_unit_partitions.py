"""Unit CI partitions must execute an exact, current, whole-file cover."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ci/partition_unit_tests.py"
spec = importlib.util.spec_from_file_location("unit_partitions", SCRIPT)
assert spec and spec.loader
partition = importlib.util.module_from_spec(spec)
spec.loader.exec_module(partition)


def sample_nodes():
    return [f"tests/unit/{folder}test_case_{index}.py::TestCase::test_value[value-{case}]"
            for folder in ("", "nested/deeper/") for index in range(8) for case in range(3)]


def manifests(nodes=None):
    nodes = sorted(nodes or sample_nodes())
    return [{"schema": 1, "partition": i, "partition_count": 2, "revision": "commit-a",
             "mode": "run", "exit_code": 0, "full_collection": nodes,
             "collection_sha256": partition.collection_hash(nodes),
             "selected": part, "attempted": list(part)}
            for i, part in enumerate(partition.partition_nodes(nodes))]


def test_nested_parametrized_files_are_whole_deterministic_and_complete():
    nodes = sample_nodes()
    parts = partition.partition_nodes(nodes)
    assert parts == partition.partition_nodes(list(reversed(nodes)))
    partition.validate_coverage(nodes, parts)
    assert set(parts[0]).isdisjoint(parts[1])
    assert set(parts[0] + parts[1]) == set(nodes)
    for part in parts:
        for node in part:
            assert [n for n in nodes if partition.file_of(n) == partition.file_of(node)] == [
                n for n in part if partition.file_of(n) == partition.file_of(node)]
    assert partition.verify_manifests(manifests())['verified'] is True
    with pytest.raises(ValueError, match='different source revision'):
        partition.verify_manifests(manifests(), expected_revision='another-commit')


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'extra', 'split-file'])
def test_invalid_partition_coverage_is_rejected(damage):
    nodes = sample_nodes()
    parts = partition.partition_nodes(nodes)
    if damage == 'missing':
        parts[0].pop()
    elif damage == 'duplicate':
        parts[0].append(parts[0][0])
    elif damage == 'extra':
        parts[0].append('tests/unit/uncollected.py::test_uncollected')
    else:
        parts[1].append(parts[0].pop())
    with pytest.raises(ValueError):
        partition.validate_coverage(nodes, parts)


@pytest.mark.parametrize('damage', ['missing-job', 'duplicate-job', 'failed-job', 'collect-only',
    'different-revision', 'different-collection', 'bad-hash', 'missing-attempt', 'duplicate-attempt',
    'selected-omission', 'bool-partition', 'wrong-schema'])
def test_manifest_verification_fails_closed(damage):
    values = copy.deepcopy(manifests())
    if damage == 'missing-job': values.pop()
    elif damage == 'duplicate-job': values[1] = values[0]
    elif damage == 'failed-job': values[0]['exit_code'] = 1
    elif damage == 'collect-only': values[0]['mode'] = 'collect'
    elif damage == 'different-revision': values[1]['revision'] = 'commit-b'
    elif damage == 'different-collection': values[1]['full_collection'] = values[1]['full_collection'][:-1]
    elif damage == 'bad-hash': values[0]['collection_sha256'] = 'bad'
    elif damage == 'missing-attempt': values[0]['attempted'].pop()
    elif damage == 'duplicate-attempt': values[0]['attempted'].append(values[0]['attempted'][0])
    elif damage == 'selected-omission': values[0]['selected'].pop()
    elif damage == 'bool-partition': values[0]['partition'] = False
    elif damage == 'wrong-schema': values[0]['schema'] = 99
    with pytest.raises(ValueError): partition.verify_manifests(values)


@pytest.mark.parametrize('node', ['', '../test_x.py::test_x', '/tests/unit/test_x.py::test_x',
    'tests/integration/test_x.py::test_x', 'tests/unit/../test_x.py::test_x',
    'tests\\unit\\test_x.py::test_x'])
def test_unsafe_or_nonunit_test_identity_is_rejected(node):
    with pytest.raises(ValueError): partition.file_of(node)


def child(script, arguments, cwd):
    env = dict(os.environ)
    env.pop('PYTEST_ADDOPTS', None)
    env.pop('PYTEST_CURRENT_TEST', None)
    return subprocess.run([sys.executable, '-B', str(script), *arguments], cwd=cwd,
                          env=env, capture_output=True, text=True, timeout=90)


def test_real_partition_runs_preserve_skips_parameters_and_nested_files(tmp_path):
    repo = tmp_path / 'repo'
    script = repo / 'scripts/ci/partition_unit_tests.py'
    script.parent.mkdir(parents=True)
    shutil.copyfile(SCRIPT, script)
    for index in range(8):
        path = repo / 'tests/unit' / ('nested/deep' if index % 2 else '') / f'test_actual_{index}.py'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('import pytest\n@pytest.mark.parametrize("value", [0,1])\n'
                        'def test_value(value): assert value in (0,1)\n'
                        '@pytest.mark.skip(reason="original explicit skip")\n'
                        'def test_skip(): assert False\n', encoding='utf-8')
    values = []
    for index in range(2):
        report = repo / f'partition-{index}.json'
        result = child(script, ['--partition', str(index), '--output', str(report), '--revision', 'fixture'], repo)
        assert result.returncode == 0, result.stdout + result.stderr
        values.append(json.loads(report.read_text()))
    verdict = partition.verify_manifests(values)
    assert verdict['tests'] == 24 and verdict['files'] == 8
    # A failing test remains a failed job; manifests cannot turn it into success.
    failing = repo / 'tests/unit/test_actual_0.py'
    failing.write_text('def test_failure(): assert False\n', encoding='utf-8')
    index = partition.file_partition('tests/unit/test_actual_0.py')
    result = child(script, ['--partition', str(index), '--output', 'failed.json'], repo)
    assert result.returncode == 1
    assert json.loads((repo / 'failed.json').read_text())['exit_code'] == 1


def test_actual_recursive_collection_matches_unpartitioned_pytest(tmp_path):
    # Collect only: this does not run the full suite against the working tree.
    plain = tmp_path / 'unpartitioned.json'
    collector = tmp_path / 'collect_plain.py'
    collector.write_text('import json,sys\nfrom pathlib import Path\nimport pytest\n'
        'class Capture:\n'
        ' def pytest_collection_finish(self,session):\n'
        '  Path(sys.argv[1]).write_text(json.dumps(sorted(i.nodeid for i in session.items)))\n'
        'raise SystemExit(pytest.main(["-q","--collect-only","tests/unit"],plugins=[Capture()]))\n', encoding='utf-8')
    result = child(collector, [str(plain)], ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    expected = json.loads(plain.read_text())
    values = []
    for index in range(2):
        report = tmp_path / f'collection-{index}.json'
        result = child(SCRIPT, ['--collect-only', '--partition', str(index), '--output', str(report)], ROOT)
        assert result.returncode == 0, result.stdout + result.stderr
        values.append(json.loads(report.read_text()))
        assert values[-1]['full_collection'] == expected
        assert values[-1]['attempted'] == []
    partition.validate_coverage(expected, [value['selected'] for value in values])
    assert len(expected) > 4000
