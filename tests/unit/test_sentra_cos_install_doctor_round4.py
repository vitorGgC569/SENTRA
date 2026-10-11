"""Chat 6 installation Doctor and PDFium build contract."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sentra_remote.install_doctor import inspect_installation, shareable_doctor, request_owner_repair
from sentra_remote.installer import INSTALL_MARKER
from scripts.commander.pdfium_pin import PDFIUM_VERSION, verify_wheel, require_pdfium


def _install(root: Path) -> None:
    root.mkdir()
    (root / INSTALL_MARKER).write_text(json.dumps({
        "product": "SENTRA Desktop", "installation_id": "fixture-id",
        "owned_files": ["sentra-canvas.exe"],
    }), encoding="utf-8")


def test_doctor_denies_unowned_and_never_discloses_identity(tmp_path: Path) -> None:
    assert inspect_installation(tmp_path).status == "unowned"
    _install(tmp_path / "Commander")
    p = inspect_installation(tmp_path / "Commander")
    assert p.status == "repair_needed"
    assert p.action == "owner_approval_required"
    report = shareable_doctor(p)
    assert "fixture-id" not in json.dumps(report)
    assert report["credentials_inspected"] is False
    assert report["execution"] == "none"


def test_doctor_does_not_dispatch_without_central_owner_auth(tmp_path: Path) -> None:
    root = tmp_path / "Commander"
    _install(root)
    calls = []
    with pytest.raises(PermissionError, match="owner-authorized"):
        request_owner_repair(root, owner_id="owner", operation_id="op-1",
                             authorize=None, dispatch=lambda *_: calls.append(True))
    with pytest.raises(PermissionError, match="denied"):
        request_owner_repair(root, owner_id="owner", operation_id="op-1",
                             authorize=lambda *_: False, dispatch=lambda *_: calls.append(True))
    assert calls == []


def test_doctor_host_bound_positive_admission_with_owner_identity(tmp_path: Path) -> None:
    root = tmp_path / "Commander"
    _install(root)
    grants = []
    result = request_owner_repair(
        root, owner_id="verified-host-owner", operation_id="durable-op",
        authorize=lambda owner, op, identity: grants.append((owner, op, identity)) or True,
        dispatch=lambda path, operation: (path, operation),
    )
    assert result == (root.resolve(), "durable-op")
    assert grants == [("verified-host-owner", "durable-op", "fixture-id")]


def test_doctor_rejects_marker_swap_even_after_host_authorization(tmp_path: Path) -> None:
    root = tmp_path / "Commander"
    _install(root)
    dispatches = []
    def approve(owner, op, identity):
        marker = root / INSTALL_MARKER
        data = json.loads(marker.read_text())
        data["installation_id"] = "another-install"
        marker.write_text(json.dumps(data))
        return True
    with pytest.raises(PermissionError, match="changed"):
        request_owner_repair(root, owner_id="owner", operation_id="operation",
                             authorize=approve, dispatch=lambda *_: dispatches.append(True))
    assert not dispatches


def test_doctor_bad_ownership_manifest_is_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "Commander"
    _install(root)
    marker = root / INSTALL_MARKER
    data = json.loads(marker.read_text())
    data["owned_files"] = ["../outside"]
    marker.write_text(json.dumps(data))
    assert inspect_installation(root).action == "deny"


def test_pinned_pdfium_package_and_corrupt_wheel_fail_closed(tmp_path: Path) -> None:
    assert PDFIUM_VERSION == "4.30.0"
    require_pdfium()
    wheel = tmp_path / "pypdfium2-4.30.0-py3-none-win_amd64.whl"
    wheel.write_bytes(b"wrong wheel content")
    with pytest.raises(ValueError, match="SHA256"):
        verify_wheel(wheel)


def test_repair_admission_uses_real_central_sqlite_grant_and_revocation(tmp_path: Path) -> None:
    from sentra_mcp.services.authorization import AuthorizationService
    root = tmp_path / "Commander"
    _install(root)
    service = AuthorizationService(tmp_path / "central-sqlite")
    owner = "authenticated-owner"
    calls = []
    def authority(bound_owner: str, op: str, installation_id: str) -> bool:
        return service.authorize(
            bound_owner, principal_type="user", principal_id=bound_owner,
            capability="release.repair", scope_type="device",
            scope_id=installation_id, local_owner=False,
            context={"interactive": True},
        )["allowed"]
    def dispatch(path: Path, op: str):
        calls.append((path, op))
        return "host-accepted"
    with pytest.raises(PermissionError, match="denied"):
        request_owner_repair(root, owner_id=owner, operation_id="host-op",
                             authorize=authority, dispatch=dispatch)
    grant = service.grant(owner, principal_type="user", principal_id=owner,
        capability="release.repair", scope_type="device", scope_id="fixture-id",
        conditions={"requires_interactive": True})
    assert request_owner_repair(root, owner_id=owner, operation_id="host-op",
                               authorize=authority, dispatch=dispatch) == "host-accepted"
    assert len(calls) == 1
    service.revoke(grant["grant_id"], owner)
    with pytest.raises(PermissionError, match="denied"):
        request_owner_repair(root, owner_id=owner, operation_id="host-op",
                             authorize=authority, dispatch=dispatch)
    assert len(calls) == 1
