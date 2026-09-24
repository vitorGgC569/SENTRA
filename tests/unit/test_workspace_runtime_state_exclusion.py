from __future__ import annotations

from workspace.sandbox import fingerprint, source_files


def test_sentra_runtime_state_is_excluded_from_source_fingerprint(tmp_path):
    source = tmp_path / "app.py"
    source.write_text("value = 1\n", encoding="utf-8")
    before = fingerprint(source_files(tmp_path))

    state = tmp_path / ".sentra"
    state.mkdir()
    (state / "context.sqlite3").write_bytes(b"runtime-state")
    (state / "audit.jsonl").write_text('{"event":"runtime"}\n', encoding="utf-8")

    files = source_files(tmp_path)
    assert set(files) == {"app.py"}
    assert fingerprint(files) == before

    source.write_text("value = 2\n", encoding="utf-8")
    assert fingerprint(source_files(tmp_path)) != before
