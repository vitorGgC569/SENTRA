"""Pacto product projections for the one authenticated Canvas shell bridge.

Root registers these actions and wraps mutations in its ShellHostRequests
journal. This module creates no journal, endpoint, machine or Grant. Catalog
operations are explicit local-owner actions, not model tool execution.
"""
from contextlib import closing

PACTO_READS = frozenset({"skill_list", "skill_review", "skill_versions", "skill_latest",
    "skill_disclose", "skill_activations", "skill_learning_review", "plugin_bundle_list", "plugin_bundle_inspect",
    "plugin_supervision", "plugin_transport_status", "plugin_connection_proof"})
PACTO_ACTIONS = PACTO_READS | frozenset({"skill_import", "skill_git", "skill_github", "skill_revoke",
    "skill_activate", "skill_deactivate", "skill_upgrade", "skill_rollback", "skill_replace", "skill_learning_stage",
    "plugin_bundle_stage", "plugin_bundle_register", "plugin_bundle_disable", "plugin_bundle_update",
    "plugin_bundle_rollback", "plugin_bundle_uninstall", "plugin_supervision_sweep"})
_SKILL = {
    "skill_list": set(), "skill_review": {"package_id"}, "skill_versions": {"name"}, "skill_latest": {"name"},
    "skill_import": {"source", "expected_sha256"},
    "skill_git": {"repository", "commit_sha", "subdirectory", "expected_sha256"},
    "skill_github": {"repository", "commit_sha", "subdirectory", "expected_sha256"},
    "skill_revoke": {"package_id", "expected_revision"},
    "skill_activate": {"package_id", "work_item_id", "agent_id"},
    "skill_deactivate": {"package_id", "work_item_id", "agent_id"},
    "skill_disclose": {"package_id", "work_item_id", "agent_id", "resource"},
    "skill_activations": {"work_item_id", "agent_id"},
    "skill_upgrade": {"name", "new_package_id", "work_item_id", "agent_id"},
    "skill_rollback": {"name", "previous_package_id", "work_item_id", "agent_id"},
    "skill_replace": {"old_package_id", "new_package_id", "work_item_id", "agent_id"},
    "skill_learning_review": {"suggestion_id"},
    "skill_learning_stage": {"suggestion_id", "expected_sha256", "expected_review_revision"},
}
_PLUGIN = {
    "plugin_bundle_list": set(), "plugin_bundle_inspect": {"package_sha256"},
    "plugin_supervision": set(), "plugin_supervision_sweep": set(), "plugin_connection_proof": set(),
    "plugin_transport_status": {"server_id"},
    "plugin_bundle_stage": {"source", "expected_sha256"},
    "plugin_bundle_register": {"package_sha256"}, "plugin_bundle_disable": {"package_sha256"},
    "plugin_bundle_uninstall": {"package_sha256"},
    "plugin_bundle_update": {"old_sha256", "new_sha256"},
    "plugin_bundle_rollback": {"current_sha256", "previous_sha256"},
}


def dispatch_pacto_product(canvas, project_id, action, params):
    """Root-only callback after bearer, owner scope and mutation reservation.

    Common space/conversation scope is validated before projecting catalog
    data. Browser parameters never contain owner/Grant/configuration/secrets.
    All executable transport operations remain MachineHost operations.
    """
    allowed = _SKILL.get(action, _PLUGIN.get(action))
    if allowed is None or not isinstance(params, dict) or set(params) - (allowed | {"space_id", "conversation_id"}):
        raise ValueError("unknown Pacto product action/fields")
    workspace = canvas.store.workspace(project_id)
    host = canvas._machine_service()
    control, owner, root = host.control, host.owner, workspace["path"]
    p = {k: v for k, v in params.items() if k in allowed}
    if params.get("space_id") is not None:
        control.shell.get_space(params["space_id"], owner, project_id=project_id)
    if params.get("conversation_id") is not None:
        with closing(control.store.connect("shell")) as db:
            control.shell._entity(db, owner, project_id, "conversation", params["conversation_id"],
                                  space_id=params.get("space_id"))
    if "work_item_id" in p:
        work = control.work_item_info(p["work_item_id"], owner)
        if work.get("metadata", {}).get("workspace_id") != project_id or work.get("assignee_agent_id") != p.get("agent_id"):
            raise PermissionError("Skill WorkItem/project/assignee mismatch")
        canvas.store.resource("agents", p["agent_id"], project_id)
    if action.startswith("skill_"):
        library = control.skill_library
        if action in {"skill_learning_review", "skill_learning_stage"}:
            from pathlib import Path
            from .learning_skills import ReviewedLearningSkills
            learning = library._learning_sources.get((owner, str(Path(root).resolve(strict=True))))
            if learning is None:
                raise PermissionError("protected Selo learning not configured for this project")
            facade = ReviewedLearningSkills(control=control, learning=learning, owner=owner,
                workspace=root, workspace_id=project_id)
            return facade.review(**p) if action == "skill_learning_review" else facade.stage(**p)
        if action == "skill_import":
            p["path"] = p.pop("source")
        if action == "skill_disclose":
            if "resource" in p:
                p["path"] = p.pop("resource")
            return library.disclose(owner, root, **p)
        if action == "skill_activations":
            return library.disclose(owner, root, **p)
        method = {"skill_list": "list", "skill_import": "import_local", "skill_git": "import_git",
            "skill_github": "import_github", "skill_review": "review", "skill_versions": "versions",
            "skill_latest": "latest", "skill_revoke": "revoke", "skill_activate": "activate",
            "skill_deactivate": "deactivate", "skill_upgrade": "upgrade_activation",
            "skill_rollback": "rollback_activation", "skill_replace": "replace_activation"}[action]
        if action == "skill_rollback":
            p["approved"] = True  # authenticated owner's explicit action; zero Grants
        return getattr(library, method)(owner, root, **p)
    if action == "plugin_connection_proof":
        return canvas.center_plugin_proof(project_id)
    if action == "plugin_transport_status":
        from .mcpb_lifecycle import MCPBLifecycleService
        return MCPBLifecycleService(control).transport_status(owner, root, **p)
    if action in {"plugin_bundle_update", "plugin_bundle_rollback", "plugin_bundle_uninstall"}:
        method = {"plugin_bundle_update": "update", "plugin_bundle_rollback": "rollback", "plugin_bundle_uninstall": "uninstall"}[action]
        return getattr(control.bundle_catalog, method)(owner, root, governance=control.governance, approved=True, **p)
    mode = {"plugin_bundle_list": "list", "plugin_bundle_inspect": "inspect", "plugin_bundle_stage": "stage",
        "plugin_bundle_register": "register", "plugin_bundle_disable": "disable",
        "plugin_supervision": "supervision", "plugin_supervision_sweep": "supervision_sweep"}[action]
    return canvas.center_plugin_bundles(project_id, action=mode, **p)
