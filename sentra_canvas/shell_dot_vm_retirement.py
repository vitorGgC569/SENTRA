"""Read-only, exact-identity VirtualBox/VDI retirement proof for a Dot.

A preflight is never a deletion authorization. The current central VirtualBox
executor does not publish unregister/delete; do not bypass its effect fence.
"""
from pathlib import Path
import uuid

from .shell_dot_vm import VmStore


def _inside(candidate, parent):
    try:
        return candidate.is_relative_to(parent)
    except (ValueError, OSError):
        return False


class DotVmRetirementInspector:
    def __init__(self, retirement):
        self.retirement = retirement
        self.control = retirement.control
        self.owner = retirement.owner

    def preview(self, project_id, dot, *, client=None):
        value = VmStore(self.control, self.owner).get(project_id, dot["dot_id"])
        result = {"project_id": project_id, "dot_id": dot["dot_id"],
            "configured": bool(value), "identity_verified": False,
            "poweroff_verified": False, "disk_ownership_verified": False,
            "vm_removed": False, "vdi_removed": False, "reservation_released": False,
            "deletion_available": False, "automatic_retry": False,
            "physical_effect_performed": False, "blockers": []}
        if not value:
            result["status"] = "no_vm_reserved"
            return result
        blockers = result["blockers"]
        expected = uuid.uuid5(uuid.NAMESPACE_URL, "|".join(
            (self.owner, project_id, dot["dot_id"])))
        vm_id = str(expected)
        result["vm_id"] = vm_id
        raw_base = Path(self.control.durable.root) / "dot-vms"
        expected_base = raw_base.resolve()
        expected_name = "SENTRA-Dot-" + expected.hex[:16]
        expected_folder = expected_base / expected_name
        # Never accept a client-provided UUID or base folder as authority.
        if (value.get("vm_id") != vm_id or value.get("root_dot_id") != dot["dot_id"] or
                value.get("agent_id") != dot["agent_id"] or
                value.get("marker") != "SENTRA-DOT:" + vm_id or
                value.get("name") != expected_name or
                not value.get("base_folder") or
                Path(value["base_folder"]).resolve() != expected_base):
            blockers.append("reservation_identity_mismatch")
            result["status"] = "blocked"
            return result
        if raw_base.is_symlink() or expected_folder.is_symlink():
            blockers.append("symlinked_vm_folder")
            result["status"] = "blocked"
            return result
        if client is None:
            from sentra_executors.virtualbox_vm import VirtualBoxClient, executable
            executable_path = executable()
            if not executable_path:
                blockers.append("virtualbox_unavailable")
                result["status"] = "blocked"
                return result
            client = VirtualBoxClient(executable_path)
        try:
            from sentra_executors.virtualbox_vm import VirtualBoxBinding
            binding = VirtualBoxBinding(vm_id, value["marker"], None)
            registered = client.run("list", "vms", physical=False)
            # Treat absence as uncertain until the owned directory and every
            # disk are independently inventoried; no reservation cleanup.
            if "{" + vm_id + "}" not in registered.lower():
                blockers.append("uuid_not_registered_inventory_needs_reconciliation")
                result["status"] = "blocked"
                return result
            info = client.status(binding)
            if (str(info.get("UUID", "")).lower() != vm_id or
                    info.get("description") != value["marker"] or
                    info.get("name") != expected_name or
                    not info.get("CfgFile")):
                blockers.append("hypervisor_identity_mismatch")
                result["status"] = "blocked"
                return result
            configured = Path(info["CfgFile"]).resolve()
            if configured.parent != expected_folder.resolve():
                blockers.append("vbox_config_directory_mismatch")
                result["status"] = "blocked"
                return result
            result["identity_verified"] = True
            result["vm_state"] = str(info.get("VMState") or "unknown")
            result["poweroff_verified"] = result["vm_state"] == "poweroff"
            if not result["poweroff_verified"]:
                blockers.append("vm_not_powered_off")
            disks = client.disk_attachments(binding)
            result["disk_count"] = len(disks)
            if not disks:
                blockers.append("disk_inventory_empty")
            else:
                identities = set()
                for disk in disks:
                    uid = str(disk.get("disk_uuid") or "").lower()
                    original = Path(str(disk.get("location") or ""))
                    path = original.resolve()
                    if (not uid or uid in identities or disk.get("parent_uuid") or
                            path.suffix.lower() != ".vdi" or
                            not _inside(path, expected_folder.resolve()) or
                            not path.is_file() or original.is_symlink() or
                            path.stat().st_nlink != 1):
                        blockers.append("unsafe_disk_identity_or_ownership")
                        break
                    identities.add(uid)
            # Even with UUID, marker and disk paths validated, a separate
            # hypervisor-wide proof of *non-shared* media is still required.
            blockers.append("shared_medium_exclusivity_not_attested")
            blockers.append("central_vm_delete_capability_not_implemented")
        except (OSError, ValueError, RuntimeError, ImportError, KeyError) as exc:
            blockers.append("virtualbox_probe_failed:" + type(exc).__name__)
        result["disk_paths_within_dot_folder"] = bool(result.get("disk_count")) and not any(
            blocker == "unsafe_disk_identity_or_ownership" for blocker in blockers)
        # Path ownership cannot independently prove VirtualBox-wide exclusivity.
        result["disk_ownership_verified"] = False
        result["status"] = "blocked"
        return result
