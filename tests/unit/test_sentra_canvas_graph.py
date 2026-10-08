"""SQLite graph state must survive window restarts and reject workspace crossing."""
from pathlib import Path
import pytest
from sentra_canvas.service import Canvas

def test_canvas_graph_notes_links_and_persistence(tmp_path):
    app=Canvas(tmp_path)
    try:
        alpha=app.create_workspace("alpha")["id"]
        beta=app.create_workspace("beta")["id"]
        cmd=app.create_terminal(alpha,"shell_a","cmd")
        agent=app.create_agent(alpha,"worker_a","sentra/model",start=False)
        graph=app.graph_detail(alpha)
        assert len(graph["nodes"])==2
        a,b=graph["nodes"]
        assert {a["kind"],b["kind"]}=={"terminal","agent"}
        link=app.graph_link(alpha,a["id"],b["id"])
        assert app.graph_link(alpha,a["id"],b["id"])["id"]==link["id"]
        moved=app.graph_move(alpha,a["id"],789,324)
        assert moved["x"]==789 and moved["y"]==324
        note=app.graph_note(alpha,"Roadmap","Contexto local",360,460)
        assert note["kind"]=="note"
        app.graph_update_note(alpha,note["id"],"Aprovação pendente")
        with pytest.raises(PermissionError):
            app.graph_move(beta,a["id"],100,100)
        with pytest.raises(PermissionError):
            app.graph_link(beta,a["id"],b["id"])
        with pytest.raises(ValueError):
            app.graph_move(alpha,a["id"],float("nan"),0)
        assert len(app.graph_detail(alpha)["nodes"])==3
        assert app.graph_detail(beta)["nodes"]==[]
        app.terminal_close(alpha,cmd["id"])
    finally:
        app.shutdown()
    reopened=Canvas(tmp_path)
    try:
        graph=reopened.graph_detail(alpha)
        assert len(graph["nodes"])==3
        assert graph["links"][0]["id"]==link["id"]
        assert next(n for n in graph["nodes"] if n["id"]==a["id"])["x"]==789
        assert next(n for n in graph["nodes"] if n["id"]==note["id"])["body"]=="Aprovação pendente"
        reopened.graph_remove_note(alpha,note["id"])
        assert len(reopened.graph_detail(alpha)["nodes"])==2
    finally:
        reopened.shutdown()
