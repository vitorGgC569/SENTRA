"""Exact host-enrolled writable base VDI identity; no disk/config mutations.

The approval envelope lives ONLY in the existing protected VM configuration.
A candidate or renderer-provided JSON is not enrollment. This module never
persists it, grants a capability or changes a VirtualBox attachment.

Only a single dynamic base VDI is supported here. Differencing media require
an approved, hash-verified parent chain and remain explicitly refused.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import struct
import uuid

from .rpa import ExecutorFailure


_FIELDS = frozenset({"vm_id", "marker_sha256", "config_path", "storage_root", "disk_path",
                     "disk_uuid", "capacity_bytes", "controller", "port", "device",
                     "file_device", "file_inode", "identity_sha256", "head_kind", "parent_chain"})


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _uuid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value or uuid.UUID(value).int == 0:
        raise ValueError("canonical_storage_uuid_required")
    return value


def _local_path(value, *, directory=False):
    if not isinstance(value, (str, Path)):
        raise ValueError("absolute_enrolled_storage_path_required")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or str(path).startswith(("\\\\", "//")):
        raise ValueError("absolute_local_storage_path_required")
    # Resolve only after rejecting aliases which could lead outside enrollment.
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
            raise ValueError("linked_storage_path_refused")
    resolved = path.resolve(strict=True)
    if resolved == Path(resolved.anchor) or (not resolved.is_dir() if directory else not resolved.is_file()):
        raise ValueError("existing_enrolled_storage_path_required")
    return resolved


def _identity(path):
    """Hash immutable geometry/UUID fields, NOT changing guest data or block map."""
    with path.open("rb") as source:
        status = os.fstat(source.fileno())
        header = source.read(512)
        if len(header) != 512 or struct.unpack_from("<II", header, 64) != (0xBEDA107F, 0x10001):
            raise ValueError("supported_base_vdi_header_required")
        # Creation UUID + parent/link UUIDs are fixed. Modification UUID and
        # allocated-block count legitimately change while Setup writes the disk.
        geometry = {"version": struct.unpack_from("<II", header, 64),
                    "header_size": struct.unpack_from("<I", header, 72)[0],
                    "image_type": struct.unpack_from("<I", header, 76)[0],
                    "offsets": struct.unpack_from("<II", header, 340),
                    "capacity": struct.unpack_from("<Q", header, 368)[0],
                    "block_geometry": struct.unpack_from("<III", header, 376),
                    "creation_uuid": str(uuid.UUID(bytes_le=header[392:408])),
                    "parent_fields": header[424:456].hex()}
    if geometry["image_type"] != 1 or geometry["parent_fields"] != "0" * 64:
        raise ValueError("approved_parent_chain_not_supported")
    if not status.st_ino or not status.st_dev or status.st_nlink != 1:
        raise ValueError("stable_storage_file_identity_required")
    return geometry, status, _digest(geometry)


def storage_binding_candidate(client, binding, cfg, *, storage_root):
    """Read-only candidate for an owner review; it is NOT installed/enrolled."""
    _uuid(binding.vm_id)
    if not isinstance(binding.marker, str) or not binding.marker:
        raise ValueError("configured_vm_marker_required")
    info = client.status(binding)  # Existing client verifies UUID + description.
    base = _local_path(cfg["base_folder"], directory=True)
    folder = _local_path(base / cfg["name"], directory=True)
    config_path = _local_path(info.get("CfgFile", ""))
    if folder.parent != base or config_path.parent != folder or config_path.suffix.lower() != ".vbox":
        raise ExecutorFailure("virtualbox_owned_config_path_changed")
    root = _local_path(storage_root, directory=True)
    disks = client.disk_attachments(binding)
    if len(disks) != 1:
        raise ExecutorFailure("virtualbox_install_requires_one_owned_virtual_disk")
    disk = disks[0]
    if (disk.get("controller") != "SATA" or type(disk.get("port")) is not int or disk["port"] != 0
            or type(disk.get("device")) is not int or disk["device"] != 0 or disk.get("parent_uuid")
            or info.get("SATA-ImageUUID-0-0") != disk.get("disk_uuid")):
        raise ExecutorFailure("virtualbox_disk_binding_changed")
    path = _local_path(disk.get("location", ""))
    if path.parent != root or path.suffix.lower() != ".vdi":
        raise ExecutorFailure("virtualbox_exact_storage_root_required")
    geometry, status, identity_hash = _identity(path)
    if geometry["creation_uuid"] != _uuid(disk.get("disk_uuid")) or geometry["capacity"] != cfg["disk_gb"] * 1073741824:
        raise ExecutorFailure("virtualbox_disk_header_identity_changed")
    from .virtualbox_installation import inspect_vdi
    observed = inspect_vdi(path, expected_uuid=disk["disk_uuid"], expected_capacity=geometry["capacity"])
    after = path.stat()
    if (not observed["metadata_stable"] or (status.st_dev, status.st_ino, status.st_size, status.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
        raise ExecutorFailure("virtualbox_storage_inventory_changed_during_read")
    record = {"vm_id": binding.vm_id, "marker_sha256": hashlib.sha256(binding.marker.encode()).hexdigest(),
              "config_path": str(config_path), "storage_root": str(root), "disk_path": str(path),
              "disk_uuid": disk["disk_uuid"], "capacity_bytes": geometry["capacity"],
              "controller": "SATA", "port": 0, "device": 0,
              "file_device": status.st_dev, "file_inode": status.st_ino,
              "identity_sha256": identity_hash, "head_kind": "dynamic_base_vdi_v1.1", "parent_chain": []}
    return {"schema": 1, "record": record, "sha256": _digest(record), "applied": False,
            "authorization_granted": False, "installed_os_verified": False}


def enrolled_base_storage(client, binding, cfg, info):
    """Validate an exact enrollment from protected host VM configuration.

    Approval provenance must be installed by the host's owner-authorized
    configuration path; no public endpoint in this module accepts JSON approval.
    The fingerprint guards identity/geometry, not integrity of mutable OS data.
    """
    envelope = cfg.get("storage_binding")
    if (not isinstance(envelope, dict)
            or set(envelope) != {"schema", "record", "sha256", "approval_operation_id"}
            or type(envelope.get("schema")) is not int or envelope["schema"] != 1
            or not isinstance(envelope.get("record"), dict) or set(envelope["record"]) != _FIELDS
            or not isinstance(envelope.get("sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", envelope["sha256"])
            or not isinstance(envelope.get("approval_operation_id"), str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", envelope["approval_operation_id"])):
        raise ExecutorFailure("virtualbox_trusted_storage_enrollment_required")
    expected = envelope["record"]
    if _digest(expected) != envelope["sha256"] or expected["parent_chain"] != [] or expected["head_kind"] != "dynamic_base_vdi_v1.1":
        raise ExecutorFailure("virtualbox_storage_enrollment_fingerprint_changed")
    verifier = getattr(binding, "storage_approval", None)
    if not callable(verifier) or verifier(binding, cfg, envelope) is not True:
        raise ExecutorFailure("virtualbox_canonical_storage_approval_required")
    candidate = storage_binding_candidate(client, binding, cfg, storage_root=expected["storage_root"])
    # CfgFile/status must agree across both fresh reads, not only by basename.
    if (candidate["sha256"] != envelope["sha256"] or candidate["record"] != expected
            or Path(info.get("CfgFile", "")).resolve() != Path(expected["config_path"])
            or info.get("SATA-ImageUUID-0-0") != expected["disk_uuid"]):
        raise ExecutorFailure("virtualbox_enrolled_storage_identity_changed")
    from .virtualbox_installation import inspect_vdi
    evidence = inspect_vdi(expected["disk_path"], expected_uuid=expected["disk_uuid"],
                           expected_capacity=expected["capacity_bytes"])
    final = Path(expected["disk_path"]).stat()
    if (not evidence["metadata_stable"] or (final.st_dev, final.st_ino)
            != (expected["file_device"], expected["file_inode"])):
        raise ExecutorFailure("virtualbox_storage_inventory_changed_during_read")
    evidence.update(storage_binding="host_enrolled_exact_base", storage_binding_sha256=envelope["sha256"],
                    storage_approval_operation_id=envelope["approval_operation_id"],
                    guest_data_integrity_verified=False, parent_chain_verified=False)
    return info, evidence
