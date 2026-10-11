"""Hermetic committed-React reader test, Node is only the JS test harness."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_main_world_rejects_ambiguous_request_message_joins():
    node=shutil.which("node")
    if node is None:
        pytest.skip("Node fixture runner unavailable")
    fixture=Path(__file__).with_name("sentra_cos_evidence_round2.cjs")
    result=subprocess.run([node,str(fixture)],capture_output=True,text=True,timeout=8)
    assert result.returncode==0, (result.stdout,result.stderr)
    assert "fixture passed" in result.stdout
