"""Final-phase tests: exact identity, quarantine, replay and human approval."""
import pytest
from sentra_mcp.services.browser_evidence import BrowserEvidenceService


def enrolled(tmp_path):
    service=BrowserEvidenceService(tmp_path)
    service.configure(extension_id='a'*32,principal='local-operator',workspace=str(tmp_path),
                      source_sha256='1'*64,enabled=True,expected_revision=0)
    return service


def observe(service,conversation='conversation-a',request='request-1234',worker='TAB-1',state='idle'):
    args=dict(extension_id='a'*32,source_sha256='1'*64,worker=worker)
    nonce=service.challenge(**args,document_id='document-1234')['nonce']
    evidence=dict(nonce=nonce,document_id='document-1234',conversation_id=conversation,
                  route_conversation_id=conversation,state=state,
                  requests=[dict(request_id=request,message_id='message-1234')])
    return args,evidence


def test_origin_survives_restart_without_time_guessing(tmp_path):
    service=enrolled(tmp_path)
    args,evidence=observe(service)
    service.observe(**args,evidence=evidence)
    again=BrowserEvidenceService(tmp_path)
    assert again.chat_access.require_allowed('local-operator','request-1234')['conversation_id']=='conversation-a'
    assert again.chat_access.chat_status('local-operator','conversation-a')['trusted'] is False


def test_conflicting_second_tab_quarantines_original_owner(tmp_path):
    service=enrolled(tmp_path)
    args,evidence=observe(service)
    service.observe(**args,evidence=evidence)
    args,evidence=observe(service,conversation='conversation-b',worker='TAB-2')
    with pytest.raises(PermissionError,match='quarantined'):
        service.observe(**args,evidence=evidence)
    with pytest.raises(PermissionError,match='quarantined'):
        BrowserEvidenceService(tmp_path).chat_access.require_allowed('local-operator','request-1234')
    with pytest.raises(PermissionError):
        service.observe(**args,evidence=evidence)


def test_revoked_and_replayed_challenges_fail_closed(tmp_path):
    service=enrolled(tmp_path)
    args,evidence=observe(service)
    service.observe(**args,evidence=evidence)
    assert service.observe(**args,evidence=evidence)['state']=='unchanged'
    with pytest.raises(PermissionError):
        service.observe(**args,evidence={**evidence,'state':'generating'})
    service.configure(extension_id='a'*32,principal='local-operator',workspace=str(tmp_path),
                      source_sha256='1'*64,enabled=False,expected_revision=1)
    with pytest.raises(PermissionError):
        service.challenge(**args,document_id='document-1234')


def test_approval_in_one_tab_cannot_be_cleared_by_another(tmp_path):
    service=enrolled(tmp_path)
    args,evidence=observe(service,state='awaiting_approval')
    service.observe(**args,evidence=evidence)
    args,evidence=observe(service,worker='TAB-2')
    service.observe(**args,evidence=evidence)
    with pytest.raises(PermissionError,match='human approval'):
        service.chat_access.require_allowed('local-operator','request-1234')
    args,evidence=observe(service,state='idle')
    service.observe(**args,evidence=evidence)
    assert service.chat_access.require_allowed('local-operator','request-1234')['allowed']


def test_private_fields_and_route_conflicts_are_not_admitted(tmp_path):
    service=enrolled(tmp_path)
    args,evidence=observe(service)
    with pytest.raises(ValueError):
        service.observe(**args,evidence={**evidence,'cookie':'private'})
    with pytest.raises(PermissionError):
        service.observe(**args,evidence={**evidence,'route_conversation_id':'conversation-b'})


def test_relay_new_message_is_blocked_while_browser_waits_for_human(tmp_path):
    from native_bridge.relay import RelayState
    from native_bridge.protocol import ChatJob
    ext,sha="a"*32,"b"*64
    conversation="chat123456789abc"
    service=BrowserEvidenceService(tmp_path/"state")
    service.configure(extension_id=ext,principal="local-operator",
                      workspace=str(tmp_path),source_sha256=sha,
                      enabled=True,expected_revision=0)
    def observe(state):
        challenge=service.challenge(extension_id=ext,source_sha256=sha,
                                    worker="TAB-123",document_id="doc123456789")
        return service.observe(extension_id=ext,source_sha256=sha,worker="TAB-123",
            evidence={"nonce":challenge["nonce"],"document_id":"doc123456789",
                      "conversation_id":conversation,"route_conversation_id":conversation,
                      "state":state,"requests":[]})
    observe("awaiting_approval")
    relay=RelayState(db_path=tmp_path/"relay.sqlite3",browser_evidence=service)
    job=ChatJob(task_id="task-webgate-1",kind="CHAT_SEND",provider="chatgpt",
                new_chat=False,conversation_url="https://chatgpt.com/c/"+conversation,
                prompt="send once")
    with pytest.raises(PermissionError,match="approval"):
        relay.submit(job)
    assert relay.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]==0
    observe("generating")
    with pytest.raises(PermissionError):
        relay.submit(job)
    observe("idle")
    assert relay.submit(job)==job.job_id
    assert relay.delivery.status(job.job_id)["state"]=="not_sent"


def test_queued_browser_message_does_not_lease_during_approval(tmp_path):
    from native_bridge.relay import RelayState
    from native_bridge.protocol import ChatJob
    ext,sha="a"*32,"b"*64
    conversation="chat123456789abc"
    service=BrowserEvidenceService(tmp_path/"state")
    service.configure(extension_id=ext,principal="local-operator",
                      workspace=str(tmp_path),source_sha256=sha,
                      enabled=True,expected_revision=0)
    def observe(state):
        challenge=service.challenge(extension_id=ext,source_sha256=sha,
                                    worker="TAB-123",document_id="doc123456789")
        return service.observe(extension_id=ext,source_sha256=sha,worker="TAB-123",
            evidence={"nonce":challenge["nonce"],"document_id":"doc123456789",
                      "conversation_id":conversation,"route_conversation_id":conversation,
                      "state":state,"requests":[]})
    relay=RelayState(db_path=tmp_path/"relay.sqlite3",browser_evidence=service)
    blocked=ChatJob(task_id="task-check-lease",kind="CHAT_SEND",provider="chatgpt",
                new_chat=False,conversation_url="https://chatgpt.com/c/"+conversation,
                prompt="first")
    relay.submit(blocked)  # No evidence yet: legacy queue admission.
    observe("awaiting_approval")
    another=ChatJob(task_id="task-other-chat",kind="CHAT_SEND",provider="chatgpt",
                new_chat=False,conversation_url="https://chatgpt.com/c/othertest123456789",
                prompt="second")
    relay.submit(another)
    selected=relay.poll("TAB-808")
    assert selected is not None and selected["job_id"]==another.job_id
    assert relay.db.execute("SELECT state FROM jobs WHERE id=?",(blocked.job_id,)).fetchone()[0]=="QUEUED"
    observe("idle")
    selected=relay.poll("TAB-809")
    assert selected is not None and selected["job_id"]==blocked.job_id
