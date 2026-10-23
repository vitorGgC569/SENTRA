"""Small actual Windows reassembly; these fixtures never execute the asset."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts.commander import preview_parts as parts


def _split(tmp_path, content=None, size=37):
    content = bytes(range(256)) * 3 + b"SENTRA preview\x00\xff" if content is None else content
    source = tmp_path / "Setup-preview.exe"
    source.write_bytes(content)
    result = parts.split_asset(source, tmp_path / "pieces", part_bytes=size)
    return source, result, content


def _manifest(result):
    return Path(result["manifest_path"])


def _join(result, output):
    executable = shutil.which("powershell.exe") if os.name == "nt" else shutil.which("pwsh")
    if not executable:
        pytest.skip("PowerShell runtime is unavailable")
    return subprocess.run([executable, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", result["helper_path"], "-OutputPath", str(output)],
        capture_output=True, text=True, timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def test_split_hashes_sizes_streaming_and_fresh_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(parts, "BUFFER_BYTES", 7)
    source, result, content = _split(tmp_path)
    manifest = json.loads(_manifest(result).read_text(encoding="utf-8"))
    assert result["status"] == "split"
    assert manifest["original"] == {"name": source.name, "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest()}
    captured = []
    for index, part in enumerate(manifest["parts"], 1):
        data = (_manifest(result).parent / part["name"]).read_bytes()
        assert part == {"name": source.name + f".part{index:04d}", "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}
        assert len(data) <= 37
        captured.append(data)
    assert b"".join(captured) == content == source.read_bytes()
    before = {p.name: p.read_bytes() for p in _manifest(result).parent.iterdir()}
    with pytest.raises(FileExistsError):
        parts.split_asset(source, _manifest(result).parent, 37)
    assert {p.name: p.read_bytes() for p in _manifest(result).parent.iterdir()} == before


@pytest.mark.parametrize("content", [b"", b"hello\x00world", bytes(range(256)) * 300], ids=["empty", "small", "binary"])
def test_powershell_restores_exact_original_without_execution(tmp_path, content):
    source, result, _ = _split(tmp_path, content, size=max(1, len(content) // 3))
    target = tmp_path / "Restored-preview.exe"
    run = _join(result, target)
    assert run.returncode == 0, run.stdout + run.stderr
    receipt = json.loads(run.stdout)
    assert receipt["status"] == "reassembled"
    assert receipt["sha256"] == hashlib.sha256(content).hexdigest()
    assert target.read_bytes() == source.read_bytes() == content
    assert not list(tmp_path.glob(".sentra-reassemble-*.tmp"))


def test_powershell_large_manifest_uses_int64_before_checking_actual_part_size(tmp_path):
    # Exercise the >2 GiB arithmetic without allocating gigabytes in every CI run.
    _, result, _ = _split(tmp_path, b"abc", size=1)
    manifest_path = _manifest(result)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["part_bytes"] = 1024 ** 3
    manifest["original"]["size_bytes"] = 3 * 1024 ** 3
    for part in manifest["parts"]:
        part["size_bytes"] = 1024 ** 3
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    target = tmp_path / "Restored-preview.exe"
    run = _join(result, target)
    assert run.returncode != 0
    assert "Part size mismatch" in run.stderr, run.stderr
    assert "System.Int32" not in run.stderr
    assert not target.exists()


@pytest.mark.parametrize("damage", ["tampered", "missing", "duplicate", "existing", "joined_hash", "traversal", "size"])
def test_powershell_refuses_damaged_or_unsafe_inputs_and_existing_destination(tmp_path, damage):
    _, result, _ = _split(tmp_path)
    manifest_path = _manifest(result)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    first = manifest_path.parent / manifest["parts"][0]["name"]
    target = tmp_path / "Restored-preview.exe"
    if damage == "tampered":
        first.write_bytes(b"!" * first.stat().st_size)
    elif damage == "missing":
        first.unlink()
    elif damage == "duplicate":
        manifest["parts"][1]["name"] = manifest["parts"][0]["name"]
    elif damage == "existing":
        target.write_bytes(b"existing owner bytes")
    elif damage == "joined_hash":
        manifest["original"]["sha256"] = "0" * 64
    elif damage == "traversal":
        manifest["parts"][0]["name"] = "../outside.part0001"
    elif damage == "size":
        first.write_bytes(b"short")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    run = _join(result, target)
    assert run.returncode != 0, run.stdout + run.stderr
    assert "Reassembly refused:" in run.stderr
    if damage == "existing":
        assert target.read_bytes() == b"existing owner bytes"
    else:
        assert not target.exists()
    assert not list(tmp_path.glob(".sentra-reassemble-*.tmp"))


@pytest.mark.parametrize("name", ["CON.exe", "file.", "setup;run.exe", "setup name.exe", parts.MANIFEST_NAME])
def test_split_rejects_unsafe_names_before_output_creation(tmp_path, name):
    source = tmp_path / name
    # Validate names before requiring even a source file to exist (CON is a
    # Windows device, not an owned test file).
    with pytest.raises(ValueError):
        parts.split_asset(source, tmp_path / "pieces", 1)
    assert not (tmp_path / "pieces").exists()


@pytest.mark.parametrize("size", [0, -1, True, 1.5, 2 * 1024 ** 3])
def test_split_rejects_invalid_part_limits_before_output_creation(tmp_path, size):
    with pytest.raises(ValueError):
        parts.split_asset(tmp_path / "Setup.exe", tmp_path / "pieces", size)
    assert not (tmp_path / "pieces").exists()


def test_split_has_bounded_part_count(tmp_path):
    source = tmp_path / "Setup.exe"
    source.write_bytes(b"x" * (parts.MAX_PARTS + 1))
    with pytest.raises(ValueError, match="part limit"):
        parts.split_asset(source, tmp_path / "pieces", 1)
    assert not (tmp_path / "pieces").exists()
    assert parts.DEFAULT_PART_BYTES == 1024 ** 3
    assert parts.MAX_PART_BYTES < 2 * 1024 ** 3


def test_split_refuses_source_changed_during_streaming(tmp_path, monkeypatch):
    source = tmp_path / "Setup.exe"
    source.write_bytes(b"original payload")
    original_open = Path.open

    class MutatingReader:
        def __init__(self, stream):
            self.stream = stream
            self.changed = False
        def __enter__(self): return self
        def __exit__(self, *args): self.stream.close()
        def fileno(self): return self.stream.fileno()
        def read(self, count):
            value = self.stream.read(count)
            if not self.changed:
                self.changed = True
                with original_open(source, "ab") as writer:
                    writer.write(b" changed")
            return value

    def opening(path, mode="r", *args, **kwargs):
        stream = original_open(path, mode, *args, **kwargs)
        return MutatingReader(stream) if path == source and mode == "rb" else stream

    monkeypatch.setattr(Path, "open", opening)
    with pytest.raises(RuntimeError, match="source changed"):
        parts.split_asset(source, tmp_path / "pieces", 4)
    assert not (tmp_path / "pieces" / parts.MANIFEST_NAME).exists()


def test_split_refuses_symlink_source_or_output_parent(tmp_path):
    source = tmp_path / "Setup.exe"
    source.write_bytes(b"safe")
    link = tmp_path / "linked.exe"
    try:
        link.symlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("symlink privilege unavailable")
    with pytest.raises(ValueError, match="linked"):
        parts.split_asset(link, tmp_path / "pieces", 2)
    directory = tmp_path / "directory"
    directory.mkdir()
    parent = tmp_path / "linked-parent"
    parent.symlink_to(directory, target_is_directory=True)
    with pytest.raises(ValueError, match="linked"):
        parts.split_asset(source, parent / "pieces", 2)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction check")
def test_windows_junction_parent_is_refused_by_split_and_reassembly(tmp_path):
    source, result, _ = _split(tmp_path)
    junction = tmp_path / "linked-pieces"
    made = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(junction), str(_manifest(result).parent)],
        capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
    assert made.returncode == 0, made.stdout + made.stderr
    try:
        with pytest.raises(ValueError, match="linked"):
            parts.split_asset(source, junction / "other", 37)
        output = tmp_path / "Restored.exe"
        alias = {**result, "helper_path": str(junction / parts.HELPER_NAME)}
        refused = _join(alias, output)
        assert refused.returncode != 0 and "Linked paths" in refused.stderr
        assert not output.exists()
    finally:
        junction.rmdir()  # Remove only this test-owned junction, never its contents.


def test_cli_emits_structured_split_and_refusal(tmp_path):
    source = tmp_path / "Setup.exe"
    source.write_bytes(b"small payload")
    command = [sys.executable, str(Path(parts.__file__)), "split", "--source", str(source),
        "--output-dir", str(tmp_path / "pieces"), "--part-bytes", "4"]
    run = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["status"] == "split"
    refused = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert refused.returncode == 2 and json.loads(refused.stderr)["status"] == "refused"
