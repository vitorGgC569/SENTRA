"""Paridade de versão da extensão: SW == content-script == manifest.

Trava contra o incidente em que bumps via `-replace` falharam silenciosamente
num arquivo, congelando o content-script na 1.3.2 enquanto o worker avançava.
Skew de versão produz diagnósticos contraditórios (telemetria ausente).
"""
import json
import re
from pathlib import Path

EXT = Path(__file__).resolve().parent.parent.parent / "edge_extension"


def _read(name: str) -> str:
    return (EXT / name).read_text(encoding="utf-8")


def test_versions_in_lockstep():
    manifest = json.loads(_read("manifest.json"))
    sw = re.search(r'OMA_SW_VERSION = "([^"]+)"', _read("service-worker.js")).group(1)
    cs = re.search(r'OMA_CS_VERSION = "([^"]+)"', _read("content-script.js")).group(1)
    assert manifest["version"] == sw == cs, (manifest["version"], sw, cs)


def test_node_syntax_if_available():
    import shutil
    import subprocess
    if not shutil.which("node"):
        return
    for name in ("service-worker.js", "content-script.js", "selectors.js", "observer.js"):
        r = subprocess.run(["node", "--check", str(EXT / name)], capture_output=True)
        assert r.returncode == 0, f"{name}: {r.stderr.decode()[:300]}"



def test_additional_checks_recovery_contract_present():
    content = _read("content-script.js")
    observer = _read("observer.js")
    assert "omaIsAdditionalChecksMessage" in content
    assert "omaStopGenerationForRecovery" in content
    assert 'omaSendMessage("Continue", [])' in content
    assert "OMA_MAX_ADDITIONAL_CHECK_RECOVERIES = 2" in content
    assert "omaIsAdditionalChecksMessage(text)" in observer
    assert "ADDITIONAL_CHECKS_LOOP" in observer
    assert "omaRecoverAdditionalChecks()" in observer
