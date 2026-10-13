"""Reviewed protected Selo learning -> inert pinned SkillLibrary package.

The host composes this facade from its existing SeloHostFacade.learning;
browser/model never supplies files, owner, manifests, reviewer or Grants.
"""
from pathlib import Path
import re
from .skill_library import _digest
from sentra_core.conversations import _encode


class ReviewedLearningSkills:
    def __init__(self, *, control, learning, owner, workspace, workspace_id):
        from sentra_quality.learning_runtime import ProtectedLearningStore
        if (not isinstance(learning, ProtectedLearningStore) or learning.state.owner != owner
                or learning.state.workspace_id != workspace_id or learning.state.store is not control.store):
            raise PermissionError("same protected central Selo learning source required")
        self.control, self.learning, self.owner = control, learning, owner
        self.root, self.project_id = str(Path(workspace).resolve(strict=True)), workspace_id
        self.library = control.skill_library
        self.library._learning_sources[(owner, self.root)] = learning

    def review(self, suggestion_id):
        item = self.learning.get(self.owner, suggestion_id)
        if item["workspace_id"] != self.project_id:
            raise PermissionError("learning belongs to another project")
        bundle = self.learning.review_bundle(self.owner, suggestion_id)
        candidate = self.learning.to_skill_files(self.owner, suggestion_id)
        return {**bundle, "review_revision": candidate["review_revision"],
                "validity": candidate["validity"], "quality_gate": candidate["quality_gate"],
                "cost_event_ids": candidate["cost_event_ids"], "activated": False}

    def stage(self, suggestion_id, *, expected_sha256, expected_review_revision):
        candidate = self.learning.to_skill_files(self.owner, suggestion_id)
        item = self.learning.get(self.owner, suggestion_id)
        manifest = candidate["capability_manifest"]
        capabilities = manifest.get("capabilities")
        if (item["workspace_id"] != self.project_id or candidate["package_sha256"] != expected_sha256
                or _digest(candidate["files"]) != expected_sha256
                or candidate["review_revision"] != expected_review_revision
                or candidate["validity"]["expires_at"] <= self.learning.clock()
                or manifest.get("package_sha256") != expected_sha256
                or not isinstance(capabilities, list) or len(capabilities) > 128
                or any(not isinstance(cap, str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", cap) for cap in capabilities)):
            raise PermissionError("learning SHA/review/validity/capability manifest differs")
        # Both durable staging steps precede activation. import_files is inert;
        # a crash before binding leaves selo provenance
        # unavailable to the guard, never an unrestricted ordinary Skill.
        package = self.library.import_files(self.owner, self.root, candidate["files"],
            source=candidate["source"], expected_sha256=expected_sha256)
        with self.library._db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT suggestion_id,review_revision,protected_manifest FROM skill_learning_bindings "
                "WHERE owner=? AND workspace=? AND package_id=?", (self.owner, self.root, expected_sha256)).fetchone()
            if existing is not None and (existing["suggestion_id"], existing["review_revision"]) != (suggestion_id, expected_review_revision):
                raise PermissionError("learning package already bound to a different review")
            db.execute("INSERT OR IGNORE INTO skill_learning_bindings VALUES(?,?,?,?,?,?)",
                (self.owner, self.root, expected_sha256, suggestion_id, expected_review_revision, _encode(manifest)))
        return {**package, "suggestion_id": suggestion_id, "review_revision": expected_review_revision,
                "capability_manifest": manifest, "activated": False, "grants_created": False}

    def activate(self, *, package_id, work_item_id, agent_id):
        # Normal SkillLibrary activation now repeats the live learning guard.
        return self.library.activate(self.owner, self.root, package_id, work_item_id, agent_id)
