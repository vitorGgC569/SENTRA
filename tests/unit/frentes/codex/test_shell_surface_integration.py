"""Exercise the real Canvas bridge for optional surfaces and authority."""
import pytest
from sentra_canvas.service import Canvas
from sentra_canvas.store import Denied

@pytest.fixture
def app(tmp_path):
    canvas=Canvas(tmp_path/"project",state_dir=tmp_path/"state",principal="closure-review")
    try:yield canvas
    finally:canvas.shutdown()

def scope(app):
    pid=app.create_workspace("Closure")["id"]
    app.create_agent(pid,"ReviewDot","sentra/test-one","worker",start=False)
    return pid

def snapshot(control):
    with control.store.connect("authorization") as db:
        grants=db.execute("SELECT COUNT(*) FROM authorization_grants").fetchone()[0]
    with control.durable.lock:
        operations=control.durable.db.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
    return operations,grants

def test_home_and_surface_reads_use_real_bridge_without_enabling(app):
    pid=scope(app)
    home=app.shell_bridge({"action":"home","project_id":pid})
    assert home["ok"] and home["value"]["dots"]
    assert home["value"]["network"]["enabled"] is False
    assert home["value"]["network"]["listening"] is False
    assert home["value"]["optional_surfaces"]["action"]=="capabilities_home"
    assert not (app.state_dir/"federation").exists()
    control=app._shell_service()
    before=snapshot(control)
    assert app.shell_bridge({"action":"network_home","project_id":pid})["value"]["enabled"] is False
    optional=app.shell_bridge({"action":"capabilities_connectors","project_id":pid})
    assert optional["ok"] and optional["value"]["connectors"]
    assert snapshot(control)==before
    assert not (app.state_dir/"federation").exists()

def test_renderer_authority_and_package_paths_rejected_before_effect(app):
    pid=scope(app)
    app.shell_bridge({"action":"home","project_id":pid})
    control=app._shell_service()
    before=snapshot(control)
    for field,value in (("principal_id","foreign-agent"),("principal_type","agent"),
                        ("grant_id","invented-grant"),("owner","foreign-owner"),
                        ("path","C:/unapproved"),("package_dir","C:/unapproved")):
        with pytest.raises((Denied,PermissionError,ValueError)):
            app.shell_bridge({"action":"capability_enable","project_id":pid,
                "package_id":"optional-connectors","request_key":"guarded-enable-"+field,
                field:value})
    assert snapshot(control)==before

def test_optional_query_failure_preserves_confirmed_home_and_sanitizes_error(app,monkeypatch):
    import sentra_canvas.shell_federation as network
    import sentra_canvas.shell_capabilities as capabilities
    pid=scope(app)
    baseline=app.shell_bridge({"action":"home","project_id":pid})["value"]
    def failed(*args):raise RuntimeError("secret-bearer-and-provider-output")
    monkeypatch.setattr(network,"home_network",failed)
    monkeypatch.setattr(capabilities,"home_capabilities",failed)
    response=app.shell_bridge({"action":"home","project_id":pid})
    assert response["ok"] is True
    assert response["value"]["dots"]==baseline["dots"]
    for field in ("network","optional_surfaces"):
        value=response["value"][field]
        assert value["status"]=="unavailable"
        assert value["query_failed"] is True and value["effect_uncertain"] is False
        assert value["reason_code"]==field+"_query_failed"
    assert "secret-bearer" not in str(response)

def test_unknown_project_does_not_create_optional_authority(app):
    with pytest.raises((Denied,FileNotFoundError,ValueError)):
        app.shell_bridge({"action":"network_home","project_id":"not-authorized-project"})
    assert not (app.state_dir/"federation").exists()
