import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from scripts.commander.build_canvas import desktop_source_inputs, validate_desktop_bundle

PROJECT = Path(__file__).resolve().parents[2] / "sentra_canvas/desktop_ui"


def fixture(tmp_path):
    project = tmp_path / "sentra_canvas/desktop_ui"
    (project / "src").mkdir(parents=True)
    (project / "scripts").mkdir()
    (project / "public").mkdir()
    for name in ("build.mjs", "build-island.mjs", "materialize.mjs", "source-inputs.mjs"):
        shutil.copy2(PROJECT / "scripts" / name, project / "scripts" / name)
    for name in ("package.json", "package-lock.json", "index.html", "island.html", "vite.config.js", "vite.island.config.js"):
        (project / name).write_text("{}", encoding="utf-8")
    (project / "src/main.jsx").write_text("export default 'initial'", encoding="utf-8")
    (project / "public/bootstrap.js").write_text("bootstrap", encoding="utf-8")
    shared = tmp_path / "integrations/orca-terminal/src"
    shared.mkdir(parents=True)
    for name in ("consumer-flow.mjs", "input-queue.mjs", "emulator-budget.mjs", "saved-register.mjs"):
        (shared / name).write_text("export default 'shared'", encoding="utf-8")
    ui = project.parent / "static"
    assets = ui / "desktop-assets"
    assets.mkdir(parents=True)
    files = {}
    for name in ("desktop.js", "desktop.css", "bootstrap.js", "chunk-a.js"):
        (assets / name).write_bytes(name.encode())
        files[name] = hashlib.sha256(name.encode()).hexdigest()
    (ui / "desktop.html").write_text('<script src="/desktop-assets/bootstrap.js"></script>')
    manifest = {"entry": "/desktop.html", "script": "/desktop-assets/desktop.js", "styles": "/desktop-assets/desktop.css",
                "files": files, "source_inputs": desktop_source_inputs(project)}
    (assets / "manifest.json").write_text(json.dumps(manifest))
    return project, ui, manifest


def test_node_and_packager_agree_on_all_source_inputs(tmp_path):
    project, _, manifest = fixture(tmp_path)
    if not shutil.which("node"):
        pytest.skip("Node required for cross-language build contract")
    script = "import {sourceInputs} from './scripts/source-inputs.mjs'; console.log(JSON.stringify(await sourceInputs(process.cwd())));"
    result = subprocess.check_output(["node", "--input-type=module", "-e", script], cwd=project, text=True)
    assert json.loads(result) == manifest["source_inputs"]


def test_byte_seal_refuses_source_which_git_would_normalize(tmp_path):
    project, _, _ = fixture(tmp_path)
    (project / "src/main.jsx").write_bytes(b"export default 'CRLF';\r\n")
    with pytest.raises(ValueError, match="Noncanonical CRLF.*src/main.jsx"):
        desktop_source_inputs(project)
    if shutil.which("node"):
        script = "import {sourceInputs} from './scripts/source-inputs.mjs'; await sourceInputs(process.cwd());"
        result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=project, capture_output=True, text=True)
        assert result.returncode != 0 and "Noncanonical CRLF" in result.stderr


@pytest.mark.parametrize("name", ["src/main.jsx", "public/bootstrap.js", "package-lock.json", "scripts/build.mjs", "scripts/build-island.mjs", "vite.island.config.js", "island.html", "../../integrations/orca-terminal/src/emulator-budget.mjs"])
def test_valid_output_hashes_cannot_certify_stale_sources(tmp_path, name):
    project, ui, _ = fixture(tmp_path)
    validate_desktop_bundle(ui)
    (project / name).write_text("changed source", encoding="utf-8")
    with pytest.raises(ValueError, match="differs from current desktop sources"):
        validate_desktop_bundle(ui)


def test_stale_prebuild_seal_cannot_materialize_or_replace_manifest(tmp_path):
    project, ui, manifest = fixture(tmp_path)
    if not shutil.which("node"):
        pytest.skip("Node required for build seal failure test")
    seal = project / "inputs.json"
    seal.write_text(json.dumps(manifest["source_inputs"], separators=(",", ":")))
    (project / "src/main.jsx").write_text("concurrent source edit")
    result = subprocess.run(["node", "scripts/materialize.mjs", str(seal)], cwd=project, capture_output=True, text=True)
    assert result.returncode != 0
    assert "sources changed during compilation" in result.stderr
    assert json.loads((ui / "desktop-assets/manifest.json").read_text()) == manifest


def test_missing_input_seal_cannot_claim_current_bundle(tmp_path):
    project, _, _ = fixture(tmp_path)
    if not shutil.which("node"):
        pytest.skip("Node required for build seal failure test")
    result = subprocess.run(["node", "scripts/materialize.mjs"], cwd=project, capture_output=True, text=True)
    assert result.returncode != 0
    assert "Build input seal required" in result.stderr


def test_dynamic_chunk_tamper_is_detected(tmp_path):
    _, ui, _ = fixture(tmp_path)
    (ui / "desktop-assets/chunk-a.js").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="stale or tampered.*chunk-a.js"):
        validate_desktop_bundle(ui)
