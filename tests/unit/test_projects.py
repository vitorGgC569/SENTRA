"""Hierarquia Project/Run/Session desacoplada do provider remoto."""
from orchestrator.projects import OmaProject, standard_conversation_name


def test_project_run_session_conversation_ids_decoupled():
    p = OmaProject(project_id="PRJ-0041", remote_name="NS Research 0041", domain="math")
    run = p.new_run("RUN-0192", "investigate regularity")
    s = run.add_session("EXEC-039", role="EXECUTOR", specialization="energy estimates")
    conv = run.attach_conversation("EXEC-039", standard_conversation_name("EXEC", 39),
                                   remote_url="https://chatgpt.com/c/abc",
                                   remote_id="abc")
    assert p.project_id == "PRJ-0041" != conv.remote_id
    assert conv.run_id == "RUN-0192"
    assert conv.conversation_key == "[EXEC-039]"
    assert s.conversation is conv
    assert standard_conversation_name("MASTER", 0) == "[MASTER]"
