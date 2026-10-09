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

def test_canvas_graph_v3_receipt_migration_is_non_destructive(tmp_path):
    """The installed v3 graph can be upgraded to v4 without losing nodes/handoffs."""
    import sqlite3
    from sentra_canvas.graph import GraphStore
    path=tmp_path/"upgrade_graph.sqlite3"
    old=GraphStore(path)
    old.sync("ws", [{"id":"terminal-a","name":"A"},{"id":"terminal-b","name":"B"}],[],[])
    nodes=old.snapshot("ws")["nodes"]
    edge=old.link("ws",nodes[0]["id"],nodes[1]["id"])
    handoff=old.record_handoff("ws",nodes[0]["id"],nodes[1]["id"],"migration payload")
    old.close()
    with sqlite3.connect(path) as connection:
        connection.execute("ALTER TABLE handoffs DROP COLUMN receipt_status")
        connection.execute("ALTER TABLE handoffs DROP COLUMN receipt_updated")
        connection.execute("PRAGMA user_version=3")
    migrated=GraphStore(path)
    try:
        assert migrated.db.execute("PRAGMA user_version").fetchone()[0]==5
        assert migrated.snapshot("ws")["links"][0]["id"]==edge["id"]
        saved=migrated.handoffs("ws")[0]
        assert saved["id"]==handoff["id"]
        assert saved["content"]=="migration payload"
        assert saved["receipt_status"]=="pending"
    finally:
        migrated.close()
