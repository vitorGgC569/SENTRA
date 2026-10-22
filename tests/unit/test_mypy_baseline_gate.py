from types import SimpleNamespace

import pytest

from scripts import check_mypy_baseline


@pytest.mark.parametrize("returncode,output", [
    (2, "Found 1 error in 1 file (errors prevented further checking)\n"),
    (1, "Found 1 error in 1 file (errors prevented further checking)\n"),
    (2, "mypy: configuration could not be read\n"),
    (1, "Found 1 error in 5 files\n"),
])
def test_incomplete_or_regressed_type_check_fails(monkeypatch, returncode, output):
    monkeypatch.setattr(check_mypy_baseline.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=returncode, stdout=output))
    assert check_mypy_baseline.main() == 1


def test_zero_type_debt_ratchet_is_preserved(monkeypatch):
    assert check_mypy_baseline.MAX_ERRORS == 0
    monkeypatch.setattr(check_mypy_baseline.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=0, stdout="Success: no issues found in 5 source files\n"))
    assert check_mypy_baseline.main() == 0
