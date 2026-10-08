"""SENTRA and Codex integration tests (no inferred model authentication)."""
from __future__ import annotations
import os
import time
from pathlib import Path
import pytest
from sentra_canvas.service import Canvas
from sentra_canvas.adapters import catalog, cli_argv

ROOT=Path(__file__).resolve().parents[2]

def test_adapter_allowlist_and_discovery(tmp_path):
    found={x["id"]:x for x in catalog(ROOT)}
    assert set(found)=={"cmd","powershell","pwsh","sentra-cli","codex","antigravity-app"}
    assert found["antigravity-app"]["session_compatible"] is False
    with pytest.raises(ValueError):
        cli_argv(ROOT,tmp_path,"../../evil")
    with pytest.raises(ValueError):
        cli_argv(ROOT,tmp_path,"antigravity-app")
    if found["sentra-cli"]["installed"]:
        argv=cli_argv(ROOT,tmp_path,"sentra-cli")
        assert "--workspace" in argv and "--no-auto-start" in argv
    if found["codex"]["installed"]:
        argv=cli_argv(ROOT,tmp_path,"codex")
        assert "-C" in argv and str(tmp_path) in argv

@pytest.mark.skipif(os.name!="nt",reason="Windows ConPTY required")
def test_real_sentra_and_codex_conpty_processes(tmp_path):
    found={x["id"]:x for x in catalog(ROOT)}
    if not (found["codex"]["installed"] and found["sentra-cli"]["installed"]):
        pytest.skip("SENTRA CLI or Codex unavailable on test machine")
    app=Canvas(tmp_path)
    app.project_dir=ROOT
    try:
        workspace=app.create_workspace("cli_probe")["id"]
        results=[]
        for name,shell in (("sentra_one","sentra-cli"),
                           ("sentra_two","sentra-cli"),
                           ("codex_one","codex")):
            row=app.create_terminal(workspace,name,shell)
            assert row["pid"] is not None
            assert row["shell"]==shell
            results.append(row)
        assert len(set(x["pid"] for x in results))==3
        outputs={}
        until=time.time()+12
        while time.time()<until:
            for row in results:
                outputs[row["name"]]=app.terminal_output(workspace,row["id"])["text"]
            if all(x.strip() for x in outputs.values()):break
            time.sleep(.3)
        # Output is diagnostic evidence only; it is NOT model inference success.
        assert any(x.strip() for x in outputs.values()), outputs
        assert len(app.graph_detail(workspace)["nodes"])==3
    finally:
        app.shutdown()

@pytest.mark.skipif(os.name!="nt",reason="Windows ConPTY required")
def test_approved_handoff_transport_and_scope(tmp_path):
    app=Canvas(tmp_path)
    try:
        ws=app.create_workspace("connected")["id"]
        other=app.create_workspace("other")["id"]
        # Mock CLI receiver: an echo-only process under ConPTY. No model is invoked.
        receiver=app._start(ws,"test_receiver","sentra-cli",
             ["cmd.exe","/Q","/K"])
        source=app.create_terminal(ws,"origin","cmd")
        outsider=app.create_terminal(other,"outsider","cmd")
        graph=app.graph_detail(ws)
        src=next(n for n in graph["nodes"] if n["resource_id"]==source["id"])
        dst=next(n for n in graph["nodes"] if n["resource_id"]==receiver["id"])
        with pytest.raises(PermissionError):
            app.handoff(ws,src["id"],dst["id"],"echo connected",True)
        app.graph_link(ws,src["id"],dst["id"])
        with pytest.raises(PermissionError):
            app.handoff(ws,src["id"],dst["id"],"echo connected",False)
        with pytest.raises(ValueError):
            app.handoff(ws,src["id"],dst["id"],"echo hello\rworld",True)
        with pytest.raises(PermissionError):
            app.handoff(other,src["id"],dst["id"],"echo nope",True)
        result=app.handoff(ws,src["id"],dst["id"],"echo HANDOFF_TRANSPORT_OK",True)
        assert result["status"]=="sent"
        assert result["model_acknowledged"] is False
        end=time.time()+6
        while time.time()<end:
            output=app.terminal_output(ws,receiver["id"])["text"]
            if "HANDOFF_TRANSPORT_OK" in output:break
            time.sleep(.1)
        assert "HANDOFF_TRANSPORT_OK" in output
        assert len(app.graph.handoffs(ws))==1
        assert app.graph.handoffs(other)==[]
        note=app.graph_note(ws,"context","Use workspace local")
        app.graph_link(ws,note["id"],dst["id"])
        app.handoff(ws,note["id"],dst["id"],"echo NOTE_HANDOFF_OK",True)
        assert len(app.graph.handoffs(ws))==2
        app.graph_remove_note(ws,note["id"])
        assert len(app.graph.handoffs(ws))==1
        app.terminal_close(ws,receiver["id"])
        app.terminal_close(ws,source["id"])
        app.terminal_close(other,outsider["id"])
    finally:
        app.shutdown()
