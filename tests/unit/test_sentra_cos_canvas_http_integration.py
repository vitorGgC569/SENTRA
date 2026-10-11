"""Real Canvas HTTP integration for CoS-inspired operator experiences."""
from __future__ import annotations
from test_sentra_runtime_canvas_center_http import running_canvas,request
from sentra_core.conversations import ConversationStore
from sentra_remote.connector_proof import ConnectorProof


def test_chat_policy_real_canvas_http_is_local_and_revision_checked(tmp_path):
    with running_canvas(tmp_path) as (app,server):
        ws=app.create_workspace("AccessLab")["id"]
        chat=app.create_agent(ws,"OperatorChat","sentra/codex/current",start=False)["conversation_id"]
        # A non-started agent may not have a distinct chat ID.
        if not chat:
            chat="chat-operator-12345678"
        url=f"/api/center/chat-access?ws={ws}&conversation_id={chat}"
        code,initial=request(server,url)
        assert code==200,initial
        assert initial["strict_policy"]=={"strict":False,"revision":0}
        assert initial["chat"]["revision"]==0
        code,_=request(server,url,authorized=False)
        assert code==401
        value={"ws":ws,"change":{"operation":"chat","conversation_id":chat,
                                  "trusted":False,"blocked":True,"expected_revision":0}}
        code,saved=request(server,"/api/center/chat-access",json_body=value)
        assert code==200 and saved["blocked"],saved
        code,replayed=request(server,"/api/center/chat-access",json_body=value)
        assert code==400
        assert "revision" in replayed["error"]
        code,strict=request(server,"/api/center/chat-access",json_body={
            "ws":ws,"change":{"operation":"strict","enabled":True,"expected_revision":0}})
        assert code==200 and strict["strict"]
        code,again=request(server,url)
        assert code==200 and again["chat"]["blocked"] and again["strict_policy"]["strict"]
        code,_=request(server,"/api/center/chat-access",json_body=value,authorized=False)
        assert code==401


def test_protected_history_search_export_scope_and_plugin_status(tmp_path):
    with running_canvas(tmp_path) as (app,server):
        ws=app.create_workspace("HistoryLab")["id"]
        other=app.create_workspace("OtherLab")["id"]
        root=app.store.workspace(ws)["path"]
        sessions=ConversationStore(app.state_dir.parent,principal=app.store.principal)
        chat=sessions.open(root)
        sessions.append(chat,"user","Finding important-moonbeam configuration steps.")
        sessions.append(chat,"assistant","Applied a redacted result.")
        code,found=request(server,f"/api/center/conversation-search?ws={ws}&q=moonbeam")
        assert code==200 and found["items"][0]["session_id"]==chat,found
        code,empty=request(server,f"/api/center/conversation-search?ws={other}&q=moonbeam")
        assert code==200 and empty["items"]==[]
        code,export=request(server,"/api/center/conversation-export",
                            json_body={"ws":ws,"conversation_id":chat})
        assert code==200 and export["complete"] and "moonbeam" in export["content"]
        code,_=request(server,"/api/center/conversation-export",
                       json_body={"ws":other,"conversation_id":chat})
        assert code==403
        code,_=request(server,"/api/center/conversation-search?ws="+ws+"&q=moonbeam",
                       authorized=False)
        assert code==401
        proof=ConnectorProof(app.state_dir.parent)
        code,view=request(server,f"/api/center/plugin-proof?ws={ws}")
        assert code==200 and view["plugin_installed_in_chatgpt"]=="unverified"
