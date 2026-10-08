import json
import os
import sqlite3
from pathlib import Path

import pytest

from sentra_canvas.service import Canvas
from sentra_canvas.validation import normalize_checks,verify_files
from tests.unit.test_canvas_task_queue import team,wait,terminal


def test_check_bounds_and_text_line_endings(tmp_path):
    for checks in ([{"path":"../outside","text":"value"}], [{"path":"C:/outside","text":"value"}],
                   [{"path":"result","sha256":"invalid"}], [{"path":"result","text":"a","sha256":"0"*64}]):
        with pytest.raises(ValueError):normalize_checks(checks)
    with pytest.raises(ValueError,match="duplicate"):
        normalize_checks([{"path":"Output.txt","text":"a"},{"path":"output.txt","text":"a"}])
    checks=normalize_checks([{"path":"out.txt","text":"line one\nline two\n"}])
    (tmp_path/"out.txt").write_bytes(b"line one\r\nline two\r\n")
    report,_=verify_files(tmp_path,checks)
    assert report["passed"]
    (tmp_path/"out.txt").write_text("wrong",encoding="utf-8")
    assert not verify_files(tmp_path,checks)[0]["passed"]


def test_output_link_cannot_verify_a_file_outside_workspace(tmp_path):
    outside=tmp_path/"outside";outside.write_text("private",encoding="utf-8")
    root=tmp_path/"workspace";root.mkdir()
    try:(root/"linked.txt").symlink_to(outside)
    except OSError as exc:pytest.skip("symlink creation unavailable: "+str(exc.winerror))
    report,_=verify_files(root,normalize_checks([{"path":"linked.txt","text":"private"}]))
    assert not report["passed"] and report["checks"][0]["error"]=="outside_workspace"


@pytest.mark.skipif(os.name!="nt",reason="real protected task state and Windows CLI")
def test_real_cli_output_checks_complete_with_artifacts_and_detect_later_change(tmp_path):
    app=Canvas(tmp_path)
    try:
        ws,group,workers=team(app)
        checks=[{"path":"checked.txt","text":"PRIVATE_CHECK_OUTPUT_26"}]
        task=app.delegate(ws,group,workers[0],"[[W|checked.txt|PRIVATE_CHECK_OUTPUT_26]]",
                          "checked","sentra-cli",True,checks=checks)
        assert wait(lambda:terminal(app,ws,task))["status"]=="succeeded"
        runtime=app._runtime()
        wait(lambda:runtime.work_item(task)["state"]=="COMPLETED")
        item=runtime.work_item(task)
        gate=item["execution_state"]["quality_gate"]
        assert gate["passed"] and len(gate["evidence"])==2
        assert "PRIVATE_CHECK_OUTPUT_26" not in json.dumps(item)
        with app.store.lock:
            protected=app.store.db.execute("SELECT protected_checks FROM task_checks WHERE task_id=?",(task["id"],)).fetchone()[0]
        assert protected.startswith("dpapi:") and "PRIVATE_CHECK_OUTPUT_26" not in protected
        before=runtime.durable.run_status(task["run_id"],runtime.owner)
        count=len(before["artifacts"])
        assert app.task_verify(ws,task["id"])["status"]=="passed"
        assert len(runtime.durable.run_status(task["run_id"],runtime.owner)["artifacts"])==count
        assert app.delegate(ws,group,workers[0],task["prompt"],"checked","sentra-cli",True,checks=checks)["id"]==task["id"]
        with pytest.raises(ValueError,match="collision"):
            app.delegate(ws,group,workers[0],task["prompt"],"checked","sentra-cli",True,
                         checks=[{"path":"checked.txt","text":"different"}])
        root=Path(app.store.workspace(ws)["path"])
        (root/"checked.txt").write_text("changed later",encoding="utf-8")
        changed=app.task_verify(ws,task["id"])
        assert changed["status"]=="changed_after_validation" and changed["historical_completion"]
        assert runtime.work_item(task)["execution_state"]["quality_gate"]["passed"]
        assert runtime.work_item(task)["metadata"]["current_file_check_status"]=="changed_after_validation"
    finally:app.shutdown()


@pytest.mark.skipif(os.name!="nt",reason="real Windows CLI")
def test_failed_check_requires_repair_and_reverification_without_reexecuting(tmp_path,monkeypatch):
    app=Canvas(tmp_path)
    try:
        ws,group,workers=team(app)
        task=app.delegate(ws,group,workers[0],"[[W|repair.txt|wrong]]","repair","sentra-cli",True,
                          checks=[{"path":"repair.txt","text":"expected"}])
        assert wait(lambda:terminal(app,ws,task))["status"]=="succeeded"
        runtime=app._runtime()
        wait(lambda:runtime.work_item(task)["state"]=="REPAIRING")
        assert not runtime.work_item(task)["execution_state"]["quality_gate"]["passed"]
        monkeypatch.setattr(app,"_cli_command",lambda args:pytest.fail("reverification must not run CLI again"))
        Path(app.store.workspace(ws)["path"],"repair.txt").write_text("expected",encoding="utf-8")
        assert app.task_verify(ws,task["id"])["status"]=="passed"
        assert runtime.work_item(task)["state"]=="COMPLETED"
    finally:app.shutdown()


@pytest.mark.skipif(os.name!="nt",reason="real Windows CLI")
def test_projection_retry_reuses_committed_evidence_after_gate_failure(tmp_path,monkeypatch):
    app=Canvas(tmp_path)
    try:
        ws,group,workers=team(app)
        runtime=app._runtime()
        original=runtime.governance.record_quality_gate
        failed=[]
        def outage(*args,**kwargs):
            if not failed:
                failed.append(True)
                raise sqlite3.OperationalError("injected gate commit failure")
            return original(*args,**kwargs)
        monkeypatch.setattr(runtime.governance,"record_quality_gate",outage)
        task=app.delegate(ws,group,workers[0],"[[W|retry.txt|once]]","retry","sentra-cli",True,
                          checks=[{"path":"retry.txt","text":"once"}])
        wait(lambda:runtime.work_item(task)["state"]=="COMPLETED")
        assert failed==[True]
        artifacts=runtime.durable.run_status(task["run_id"],runtime.owner)["artifacts"]
        assert len(artifacts)==2
    finally:app.shutdown()


@pytest.mark.skipif(os.name!="nt",reason="real Windows CLI")
def test_configured_review_stage_is_preserved_after_file_checks(tmp_path):
    app=Canvas(tmp_path)
    try:
        ws,group,workers=team(app)
        app.run_control(ws,"pause")
        task=app.delegate(ws,group,workers[0],"[[W|review.txt|ready]]","review","sentra-cli",True,
                          checks=[{"path":"review.txt","text":"ready"}])
        runtime=app._runtime()
        with app._lock:
            runtime.project(task)
            with runtime.governance._connect() as db:
                db.execute("UPDATE work_items SET execution_policy_json=? WHERE work_item_id=?",
                    (json.dumps({"require_quality_gate":True,"stages":[{"id":"review","type":"review","allow_any_authorized":True}]}),task["work_item_id"]))
        app.run_control(ws,"resume")
        wait(lambda:runtime.work_item(task)["state"]=="IN_REVIEW")
        assert app.task_verify(ws,task["id"])["status"]=="policy_pending"
        assert runtime.work_item(task)["state"]=="IN_REVIEW"
    finally:app.shutdown()


@pytest.mark.skipif(os.name!="nt",reason="actual Windows CLI")
def test_file_mutation_before_artifact_registration_never_passes_quality(tmp_path,monkeypatch):
    app=Canvas(tmp_path)
    try:
        ws,group,workers=team(app)
        runtime=app._runtime()
        original=runtime.durable.register_artifact
        changed=[]
        def mutate(run,owner,path,**kwargs):
            if kwargs.get("expected_sha256") and not changed:
                changed.append(True)
                Path(path).write_text("unexpected change",encoding="utf-8")
            return original(run,owner,path,**kwargs)
        monkeypatch.setattr(runtime.durable,"register_artifact",mutate)
        task=app.delegate(ws,group,workers[0],"[[W|changing.txt|expected]]","changing","sentra-cli",True,
                          checks=[{"path":"changing.txt","text":"expected"}])
        wait(lambda:runtime.work_item(task)["state"]=="REPAIRING")
        assert changed==[True]
        assert not runtime.work_item(task)["execution_state"]["quality_gate"]["passed"]
        Path(app.store.workspace(ws)["path"],"changing.txt").write_text("expected",encoding="utf-8")
        assert app.task_verify(ws,task["id"])["status"]=="passed"
        assert runtime.work_item(task)["state"]=="COMPLETED"
    finally:app.shutdown()
