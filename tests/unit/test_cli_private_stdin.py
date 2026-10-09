"""Private task transport rejects truncated/invalid UTF-8 before any execution."""
import io
import sys

import pytest

from sentra_cli.__main__ import main


@pytest.mark.parametrize("value",[b"",b"\xff",b"a"*4001,b" "*16384+b"x",b" \n\t"])
def test_invalid_private_input_never_executes(value,monkeypatch,capsys):
    monkeypatch.setattr(sys,"stdin",io.BytesIO(value))
    assert main(["--prompt-stdin","--no-auto-start"])==2
    assert "stdin instruction" in capsys.readouterr().err


def test_real_private_input_writes_unicode_file(tmp_path,monkeypatch,capsys):
    monkeypatch.setattr(sys,"stdin",io.BytesIO("[[W|utf8.txt|café 🔒]]".encode("utf-8")))
    assert main(["--prompt-stdin","--workspace",str(tmp_path),"--state-dir",str(tmp_path/"state"),
                 "--model","sentra/model","--no-auto-start"])==0
    assert (tmp_path/"utf8.txt").read_text(encoding="utf-8")=="café 🔒"


def test_private_input_cannot_combine_two_instructions(monkeypatch):
    monkeypatch.setattr(sys,"stdin",io.BytesIO(b"never read"))
    assert main(["--prompt-stdin","--prompt","second input"])==2
