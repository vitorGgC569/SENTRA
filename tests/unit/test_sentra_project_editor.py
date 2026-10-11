"""Owner-only project editing: review, SHA CAS, confinement and explicit approval."""
import hashlib
from pathlib import Path
import pytest
from sentra_canvas.project_review import file_preview,preview_edit,save_edit
from test_sentra_runtime_canvas_center_http import running_canvas,request

SHA=lambda text: hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_editor_previews_diff_then_writes_atomically_with_revision(tmp_path):
    target=tmp_path/"main.py"
    target.write_bytes(b"old\n")
    initial=file_preview(tmp_path,"main.py")
    assert initial["sha256"]==SHA("old\n") and initial["editable"]
    prepared=preview_edit(tmp_path,"main.py",content="new\n",expected_sha256=initial["sha256"])
    assert prepared["changed"] and "-old" in prepared["diff"] and "+new" in prepared["diff"]
    assert target.read_text(encoding="utf-8")=="old\n"
    saved=save_edit(tmp_path,"main.py",content="new\n",
                    expected_sha256=initial["sha256"],state_root=tmp_path/"state")
    assert saved["written"] and not saved["grants_created"]
    assert saved["sha256"]==SHA("new\n")
    assert target.read_text(encoding="utf-8")=="new\n"
    with pytest.raises(FileExistsError,match="revision"):
        save_edit(tmp_path,"main.py",content="stale\n",
                  expected_sha256=initial["sha256"],state_root=tmp_path/"state")
    assert target.read_text(encoding="utf-8")=="new\n"
    no_change=save_edit(tmp_path,"main.py",content="new\n",
                        expected_sha256=saved["sha256"],state_root=tmp_path/"state")
    assert no_change["written"] is False


def test_editor_denies_sensitive_foreign_and_oversized_content(tmp_path):
    target=tmp_path/"good.py"
    target.write_text("original",encoding="utf-8")
    sha=SHA("original")
    (tmp_path/".env").write_text("SECRET",encoding="utf-8")
    for path in ("../good.py",".env",".git/config"):
        with pytest.raises((PermissionError,FileNotFoundError)):
            preview_edit(tmp_path,path,content="x",expected_sha256=sha)
    with pytest.raises(ValueError,match="bounded"):
        preview_edit(tmp_path,"good.py",content="x"*131073,expected_sha256=sha)
    with pytest.raises(ValueError,match="SHA-256"):
        preview_edit(tmp_path,"good.py",content="new",expected_sha256="bad")
    assert target.read_text(encoding="utf-8")=="original"


def test_canvas_http_editor_review_and_owner_confirmation(tmp_path):
    with running_canvas(tmp_path) as (app,server):
        ws=app.create_workspace("EditorAlpha")["id"]
        other=app.create_workspace("EditorBeta")["id"]
        root=Path(app.store.workspace(ws)["path"])
        target=root/"notes.md"
        target.write_bytes(b"before\n")
        sha=SHA("before\n")
        url="/api/center/project-review"
        body={"ws":ws,"path":"notes.md","action":"preview_edit",
              "content":"after\n","expected_sha256":sha}
        status,diff=request(server,url,json_body=body)
        assert status==200 and diff["write_performed"] is False
        assert len(diff["review_token"]) > 32
        assert target.read_text(encoding="utf-8")=="before\n"
        body["action"]="save"
        status,_=request(server,url,json_body={**body,"approve":True})
        assert status!=200
        body["review_token"]=diff["review_token"]
        status,_=request(server,url,json_body=body)
        assert status==403
        status,_=request(server,url,json_body={**body,"approve":True},authorized=False)
        assert status==401
        status,_=request(server,url,json_body={**body,"approve":True,"ws":other})
        assert status!=200
        status,result=request(server,url,json_body={**body,"approve":True})
        assert status==200 and result["written"]
        status,_=request(server,url,json_body={**body,"approve":True})
        assert status!=200
        status,projection=request(server,url+f"?ws={ws}&path=notes.md&action=preview")
        assert status==200 and projection["content"]=="after\n"
        status,_=request(server,url+f"?ws={ws}&path=notes.md&action=save")
        assert status!=200
