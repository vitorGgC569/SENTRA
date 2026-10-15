"""Future acceptance cases. Do not run before the integral validation gate."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from sentra_canvas.project_documents import ProjectDocuments
from sentra_canvas.project_review import ProjectWatchRegistry, _rename_identity
from sentra_collab.authority import CollaborationDenied, SnapshotConflict
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService


@pytest.fixture
def service(tmp_path):
    durable = DurableRunService(tmp_path)
    context = ContextBusService(tmp_path, store=durable.store)
    control = ControlPlaneService(durable, context)
    run = durable.create_run("owner", workspace="project")
    def space(sid, pid):
        if pid != "project" or sid not in {"space", "other"}:
            raise PermissionError("wrong Space")
        return {"space_id": sid, "project_id": pid, "run_id": run["run_id"]}
    documents = ProjectDocuments(control, owner="owner", resolve_space=space,
        resolve_run=lambda _: run["run_id"])
    yield documents, control
    context.close()
    durable.close()


def call(service, action, **payload):
    return service.dispatch(action, {"space_id": "space", **payload}, project_id="project", principal_id="alice")


def create(service, key="create"):
    return call(service, "document_create", mutation_id=key, title="Rich page", content="# Original\n", format="markdown")


def test_receipt_replay_conflict_and_restore_append_history(service):
    documents, control = service
    original = create(documents)
    assert create(documents)["receipt_id"] == original["receipt_id"]
    saved = call(documents, "document_save", document_id=original["document_id"],
                 expected_revision=1, mutation_id="save", content="# New\n")
    assert saved["revision"] == 2
    assert control.durable.operation_status(saved["operation_id"], "owner")["state"] == "SUCCEEDED"
    with pytest.raises(SnapshotConflict):
        call(documents, "document_save", document_id=original["document_id"], expected_revision=1,
             mutation_id="stale", content="lost update")
    restored = call(documents, "document_restore", document_id=original["document_id"], revision=1,
                    expected_revision=2, mutation_id="restore")
    assert restored["revision"] == 3 and restored["content"] == original["content"]
    history = call(documents, "document_history", document_id=original["document_id"])
    assert [v["revision"] for v in history["items"]] == [3, 2, 1]


def test_two_concurrent_writers_have_one_cas_winner(service):
    documents, _ = service
    original = create(documents)
    def writer(index):
        try:
            return call(documents, "document_save", document_id=original["document_id"],
                expected_revision=1, mutation_id=f"concurrent-{index}", content=str(index))
        except SnapshotConflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(writer, range(2)))
    assert sum(r is not None for r in results) == 1
    assert call(documents, "document_get", document_id=original["document_id"])["revision"] == 2


def test_document_grant_cannot_cross_space_or_resume_after_revocation(service):
    documents, control = service
    original = create(documents)
    with pytest.raises(CollaborationDenied):
        documents.dispatch("document_get", {"space_id": "other", "document_id": original["document_id"]},
            project_id="project", principal_id="alice", work_item_id=original["work_item_id"])
    grants = control.authorization.list_grants("owner", principal_type="user", principal_id="alice")["items"]
    for grant in grants:
        control.authorization.revoke(grant["grant_id"], "owner")
    with pytest.raises(CollaborationDenied):
        call(documents, "document_save", document_id=original["document_id"], expected_revision=1,
             mutation_id="revoked", content="no")
    with pytest.raises(CollaborationDenied):
        call(documents, "document_session", document_id=original["document_id"], request_key="revoked-session")


def test_tombstone_blocks_recreation_and_hierarchy_cycles(service):
    documents, _ = service
    parent = create(documents)
    child = call(documents, "document_create", mutation_id="child", title="Child", parent_id=parent["document_id"])
    with pytest.raises(ValueError):
        call(documents, "document_save", document_id=parent["document_id"], expected_revision=1,
            mutation_id="cycle", parent_id=child["document_id"])
    with pytest.raises(SnapshotConflict):
        call(documents, "document_delete", document_id=parent["document_id"], expected_revision=1, mutation_id="parent-delete")
    deleted = call(documents, "document_delete", document_id=child["document_id"], expected_revision=1, mutation_id="child-delete")
    assert deleted["deleted"]
    with pytest.raises(SnapshotConflict):
        call(documents, "document_create", document_id=child["document_id"], title="resurrect", mutation_id="recreate")


def test_renderer_authority_fields_denied(service):
    documents, _ = service
    for field in ["owner", "principal_id", "grant_id", "permission", "work_item_id", "path"]:
        with pytest.raises(CollaborationDenied):
            call(documents, "document_list", **{field: "injected"})


def test_watcher_same_directory_rename_and_project_isolation(tmp_path):
    source = tmp_path / "old.py"
    source.write_text("print('passive')\n", encoding="utf-8")
    registry = ProjectWatchRegistry()
    handle = registry.start("project", tmp_path, "old.py")
    renamed_path = tmp_path / "new.py"
    source.rename(renamed_path)
    renamed = registry.poll("project", handle["watch_id"])
    assert renamed["state"] == "renamed" and renamed["path"] == "new.py"
    assert renamed.get("previous_path") == "old.py"
    assert _rename_identity(renamed_path, renamed_path.stat(follow_symlinks=False)) is not None
    with pytest.raises(PermissionError):
        registry.poll("other", handle["watch_id"])
    registry.close("project", handle["watch_id"])
    with pytest.raises(PermissionError):
        registry.poll("project", handle["watch_id"])
