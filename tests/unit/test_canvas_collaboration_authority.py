"""Central grant authority and durable graph projection acceptance cases."""
import base64
import hashlib

import pytest

from test_sentra_runtime_canvas_center_http import running_canvas
from sentra_collab.authority import CollaborationDenied, SnapshotConflict


def scope(app):
    ws = app.create_workspace("Collaboration")["id"]
    prepared = app.collab_prepare(ws, "user-local")
    ticket = app.collab_session(ws, prepared["work_item_id"], "user-local", "write")
    authority = app._collaboration_service()
    context = authority.resolve(token=ticket["token"], workspace_id=ws)
    assert authority.consume(context, fingerprint=hashlib.sha256(ticket["token"].encode()).hexdigest())
    return ws, prepared, ticket, authority, context


def test_single_use_grants_revocation_and_snapshot_cas(tmp_path):
    with running_canvas(tmp_path) as (app, _):
        ws, prepared, ticket, authority, context = scope(app)
        with pytest.raises(CollaborationDenied):
            authority.resolve(token=ticket["token"], workspace_id=ws)
        projection = {"layout":{}, "nodes":{}, "notes":{}}
        snapshot = base64.b64encode(b"opaque-tested-by-node-boundary").decode()
        result = authority.commit(context=context, expected_revision=0,
                                  snapshot=snapshot, presentation=projection)
        assert result["revision"] == 1
        with pytest.raises(SnapshotConflict):
            authority.commit(context=context, expected_revision=0,
                             snapshot=snapshot, presentation=projection)
        app.collab_disable(ws, prepared["work_item_id"], "user-local")
        assert authority.check(context, action="write") is False
        with pytest.raises(CollaborationDenied):
            authority.commit(context=context, expected_revision=1,
                             snapshot=snapshot, presentation=projection)
        assert authority.load(ws)["revision"] == 1


def test_projection_recovers_after_commit_and_cannot_create_execution_resources(tmp_path):
    with running_canvas(tmp_path) as (app, _):
        ws, _, _, authority, context = scope(app)
        note = app.graph_note(ws, "Shared", "original")
        other = app.create_workspace("Other")["id"]
        secret = app.graph_note(other, "Private", "unchanged")
        projection = {"layout":{}, "nodes":{
            note["id"]:{"x":10,"y":20,"width":335,"height":220},
            secret["id"]:{"x":900,"y":900,"width":335,"height":220},
            "invented-agent":{"x":1,"y":1,"width":335,"height":220}},
            "notes":{note["id"]:"confirmed", secret["id"]:"cannot cross workspace"}}
        authority.commit(context=context, expected_revision=0, snapshot=base64.b64encode(b"snapshot").decode(),
                         presentation=projection)
        assert app.graph.snapshot(ws)["nodes"][0]["body"] == "original"
        recovered = app.graph_detail(ws)
        assert recovered["collaboration_revision"] == 1
        assert recovered["nodes"][0]["body"] == "confirmed"
        assert recovered["nodes"][0]["x"] == 10
        assert app.graph.snapshot(other)["nodes"][0]["body"] == "unchanged"
        assert not any(n["id"] == "invented-agent" for n in recovered["nodes"])
        app.graph_move(ws, note["id"], 30, 40)
        assert app.graph_detail(ws)["nodes"][0]["x"] == 30  # revision replay is idempotent


def test_runtime_authority_keys_and_invalid_geometry_are_rejected(tmp_path):
    with running_canvas(tmp_path) as (app, _):
        _, _, _, authority, context = scope(app)
        for projection in ({"layout":{},"nodes":{},"notes":{},"runs":{}},
                           {"layout":{},"nodes":{"__proto__":{"x":0,"y":0,"width":335,"height":220}},"notes":{}},
                           {"layout":{},"nodes":{"n":{"x":float("nan"),"y":0,"width":335,"height":220}},"notes":{}}):
            with pytest.raises(CollaborationDenied):
                authority.commit(context=context,expected_revision=0,snapshot="",presentation=projection)
