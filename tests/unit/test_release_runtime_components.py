"""Transport/ABI fixtures, never evidence of native execution or a real engine."""
import hashlib
import json

import pytest

from scripts.commander.release_components import stage_runtime_components
from sentra_code_mode.guest.inspect_wasm import FUNCTIONS
from tests.unit.test_native_payload import pe_fixture


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources(tmp_path, *, wasi=False):
    wasmtime = pytest.importorskip("wasmtime", reason="WASM fixture assembler required")
    types = {0x7f: "i32", 0x7e: "i64"}
    functions = []
    for name, (params, results) in FUNCTIONS.items():
        args = " ".join("(param " + types[item] + ")" for item in params)
        result = " ".join("(result " + types[item] + ")" for item in results)
        body = types[results[0]] + ".const 0" if results else ""
        functions.append(f'(func (export "{name}") {args} {result} {body})')
    extra = '(import "wasi_snapshot_preview1" "fd_write" (func))' if wasi else ""
    wat = '(module (import "env" "sentra_host_call" (func (param i32 i32 i32 i32) (result i32)))' + extra + '(memory (export "memory") 16 512)' + "".join(functions) + ')'
    result = {}
    for name in ("quickjs", "hcs", "rustdesk"):
        directory = tmp_path / name
        directory.mkdir()
        result[name] = directory
        if name == "quickjs":
            wasm = directory / "guest.wasm"
            wasm.write_bytes(wasmtime.wat2wasm(wat))
            (directory / "sbom.json").write_text(json.dumps({"bomFormat": "CycloneDX"}))
            (directory / "LICENSE-QuickJS").write_text("transport fixture license")
            legal = directory / "LICENSE-static-runtime"
            legal.write_text("transport fixture static runtime notice")
            (directory / "provenance.json").write_text(json.dumps({
                "guest": wasm.name, "wasm_sha256": _sha(wasm), "sbom": "sbom.json",
                "wasi_imports": [], "host_imports": ["env.sentra_host_call"],
                "legal_files": [{"path": legal.name, "sha256": _sha(legal)}]}))
        else:
            payload = directory / "fixture.exe"
            payload.write_bytes(pe_fixture())
            files = [{"path": payload.name, "sha256": _sha(payload)}]
            if name == 'rustdesk':
                library = directory / 'librustdesk.dll'
                library.write_bytes(pe_fixture(dll=True))
                files.append({"path": library.name, "sha256": _sha(library)})
            (directory / "manifest.json").write_text(json.dumps({"compiled": True,
                "executable": payload.name, "executable_sha256": _sha(payload),
                "extension": "sentra-peer-gate-v1", "stock_cli_supported": False,
                "bundle_sha256": {item['path']: item['sha256'] for item in files},
                "control_extension": "sentra-desktop-control-v1" if name == "rustdesk" else None,
                "files": files}))
    return result


def stage(tmp_path, prepared):
    target = tmp_path / "staging"
    target.mkdir()
    return stage_runtime_components(target, prepared)


def test_transport_keeps_static_licenses_and_does_not_claim_runtime_validation(tmp_path):
    prepared = sources(tmp_path)
    result = stage(tmp_path, prepared)
    assert all(item["materialized"] is True and item["validated"] is False for item in result.values())
    assert (tmp_path / "staging/runtime/quickjs/LICENSE-static-runtime").is_file()


def test_header_only_wasm_is_not_a_materialized_guest(tmp_path):
    prepared = sources(tmp_path)
    guest = prepared["quickjs"] / "guest.wasm"
    guest.write_bytes(b"\x00asm\x01\x00\x00\x00")
    proof = prepared["quickjs"] / "provenance.json"
    metadata = json.loads(proof.read_text())
    metadata["wasm_sha256"] = _sha(guest)
    proof.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="sole env.sentra_host_call"):
        stage(tmp_path, prepared)


def test_wasi_import_cannot_be_hidden_by_manifest_claim(tmp_path):
    prepared = sources(tmp_path, wasi=True)
    with pytest.raises(ValueError, match="sole env.sentra_host_call"):
        stage(tmp_path, prepared)


def test_static_licenses_are_required_for_integral_package(tmp_path):
    prepared = sources(tmp_path)
    proof = prepared["quickjs"] / "provenance.json"
    metadata = json.loads(proof.read_text())
    metadata.pop("legal_files")
    proof.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="license proofs required"):
        stage(tmp_path, prepared)


def test_static_license_bytes_must_match_provenance(tmp_path):
    prepared = sources(tmp_path)
    (prepared["quickjs"] / "LICENSE-static-runtime").write_text("modified")
    with pytest.raises(PermissionError, match="digest mismatch"):
        stage(tmp_path, prepared)


def test_compiled_claim_cannot_make_arbitrary_bytes_a_native_component(tmp_path):
    prepared = sources(tmp_path)
    (prepared['hcs'] / 'fixture.exe').write_bytes(b'MZ' + bytes(254))
    with pytest.raises(ValueError, match='PE signature'):
        stage(tmp_path, prepared)


def test_rustdesk_library_must_export_sentra_control_symbol(tmp_path):
    prepared = sources(tmp_path)
    (prepared['rustdesk'] / 'librustdesk.dll').write_bytes(pe_fixture(dll=True, export=False))
    with pytest.raises(ValueError, match='required SENTRA'):
        stage(tmp_path, prepared)
