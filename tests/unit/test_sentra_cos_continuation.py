"""SENTRA CoS continuation: local two-phase rebind, no provider replay."""
import pytest

from sentra_mcp.services.session_checkpoint import SessionCheckpointConflict
from sentra_mcp.services.durable import DurableStateConflict
from test_governance_coordination import _services


def setup_chat(tmp_path):
    durable, context, control = _services(tmp_path)
    owner="continuation-owner"
    run=durable.create_run(owner,workspace="continuation-lab")
    control.ensure_agent(run["run_id"],owner,agent_id="continuation-agent",role="builder")
    durable.bind_chat(run["run_id"],owner,agent_id="continuation-agent",
                      provider="chatgpt",conversation_id="chatgpt-old",
                      chat_id="logical-chat")
    cp=control.write_session_checkpoint(
        owner,run_id=run["run_id"],chat_id="logical-chat",
        source_instance_id="web-observer",source_epoch="epoch-1",source_seq=1,
        checkpoint={"summary":"implementation done","pending":["verify"]},
        cursor={"last_turn":19})
    return durable,context,control,owner,run["run_id"],cp


def test_prepare_requires_checkpoint_and_scopes_parallel_requests(tmp_path):
    durable,context,control,owner,run,cp=setup_chat(tmp_path)
    try:
        a=control.prepare_chat_continuation(owner,run_id=run,chat_id="logical-chat",
             target_conversation_id="chatgpt-new",request_key="k1")
        assert a["state"]=="PREPARED"
        assert a["checkpoint_id"]==cp["checkpoint_id"]
        assert a["remote_target_attested"] is False
        assert control.prepare_chat_continuation(owner,run_id=run,chat_id="logical-chat",
             target_conversation_id="chatgpt-new",request_key="k1")["continuation_id"]==a["continuation_id"]
        with pytest.raises(SessionCheckpointConflict):
            control.prepare_chat_continuation(owner,run_id=run,chat_id="logical-chat",
                target_conversation_id="chatgpt-other",request_key="k1")
        with pytest.raises(SessionCheckpointConflict):
            control.prepare_chat_continuation(owner,run_id=run,chat_id="logical-chat",
                target_conversation_id="chatgpt-other",request_key="k2")
        with pytest.raises(FileNotFoundError):
            control.reconcile_chat_continuation("other-owner",a["continuation_id"])
        with pytest.raises(PermissionError):
            control.commit_chat_continuation(owner,a["continuation_id"])
        assert control.cancel_chat_continuation(owner,a["continuation_id"],
            operator_approved=True)["state"]=="CANCELLED"
        b=control.prepare_chat_continuation(owner,run_id=run,chat_id="logical-chat",
              target_conversation_id="chatgpt-other",request_key="k2")
        assert b["continuation_id"]!=a["continuation_id"]
    finally:
        context.close();durable.close()


def test_commit_is_local_and_replay_safe(tmp_path):
    durable,context,control,owner,run,cp=setup_chat(tmp_path)
    try:
        a=control.prepare_chat_continuation(owner,run_id=run,chat_id="logical-chat",
              target_conversation_id="chatgpt-new",request_key="k1")
        done=control.commit_chat_continuation(owner,a["continuation_id"],
                                              operator_approved=True)
        assert done["state"]=="COMMITTED" and not done["idempotent_replay"]
        assert done["remote_target_attested"] is False
        chat=next(c for c in durable.run_status(run,owner)["chats"]
                  if c["chat_id"]=="logical-chat")
        assert chat["conversation_id"]=="chatgpt-new"
        assert chat["agent_id"]=="continuation-agent"
        assert control.commit_chat_continuation(owner,a["continuation_id"],
               operator_approved=True)["idempotent_replay"] is True
        assert control.reconcile_chat_continuation(owner,a["continuation_id"])["state"]=="COMMITTED"
        with pytest.raises(SessionCheckpointConflict):
            control.cancel_chat_continuation(owner,a["continuation_id"],operator_approved=True)
    finally:
        context.close();durable.close()


def test_crash_after_core_commit_reconciles_without_second_rebind(tmp_path):
    durable,context,control,owner,run,cp=setup_chat(tmp_path)
    try:
        a=control.prepare_chat_continuation(owner,run_id=run,chat_id="logical-chat",
              target_conversation_id="chatgpt-new",request_key="k1")
        control.session_checkpoints.transition_continuation(
            owner,a["continuation_id"],expected="PREPARED",state="REBINDING")
        durable.rebind_chat("logical-chat",owner,conversation_id="chatgpt-new",
                            conversation_url=None,expected_conversation_id="chatgpt-old")
        outcome=control.reconcile_chat_continuation(owner,a["continuation_id"])
        assert outcome["state"]=="COMMITTED" and outcome["binding_matches_target"]
        assert control.commit_chat_continuation(owner,a["continuation_id"],
               operator_approved=True)["idempotent_replay"]
    finally:
        context.close();durable.close()


def test_crash_before_core_commit_remains_uncertain_until_review(tmp_path):
    durable,context,control,owner,run,cp=setup_chat(tmp_path)
    try:
        a=control.prepare_chat_continuation(owner,run_id=run,chat_id="logical-chat",
              target_conversation_id="chatgpt-new",request_key="k1")
        control.session_checkpoints.transition_continuation(
            owner,a["continuation_id"],expected="PREPARED",state="REBINDING")
        outcome=control.reconcile_chat_continuation(owner,a["continuation_id"])
        assert outcome["state"]=="UNCERTAIN" and outcome["requires_operator_reconciliation"]
        with pytest.raises(SessionCheckpointConflict):
            control.commit_chat_continuation(owner,a["continuation_id"],
                                             operator_approved=True)
        assert control.cancel_chat_continuation(owner,a["continuation_id"],
                operator_approved=True)["state"]=="CANCELLED"
        assert next(c for c in durable.run_status(run,owner)["chats"]
                    if c["chat_id"]=="logical-chat")["conversation_id"]=="chatgpt-old"
    finally:
        context.close();durable.close()


def test_core_compare_and_swap_prevents_overwriting_other_rebind(tmp_path):
    durable,context,control,owner,run,cp=setup_chat(tmp_path)
    try:
        a=control.prepare_chat_continuation(owner,run_id=run,chat_id="logical-chat",
              target_conversation_id="chatgpt-new",request_key="k1")
        durable.rebind_chat("logical-chat",owner,conversation_id="another-chat",
                            conversation_url=None)
        with pytest.raises(SessionCheckpointConflict):
            control.commit_chat_continuation(owner,a["continuation_id"],
                                             operator_approved=True)
        with pytest.raises(DurableStateConflict):
            durable.rebind_chat("logical-chat",owner,conversation_id="chatgpt-new",
                                conversation_url=None,
                                expected_conversation_id="chatgpt-old")
        with pytest.raises(SessionCheckpointConflict):
            control.cancel_chat_continuation(owner,a["continuation_id"],
                                             operator_approved=True)
    finally:
        context.close();durable.close()


def test_new_checkpoint_prevents_stale_handoff(tmp_path):
    durable,context,control,owner,run,cp=setup_chat(tmp_path)
    try:
        transfer=control.prepare_chat_continuation(owner,run_id=run,chat_id="logical-chat",
            target_conversation_id="chatgpt-new",request_key="k1")
        control.write_session_checkpoint(
            owner,run_id=run,chat_id="logical-chat",
            source_instance_id="web-observer",source_epoch="epoch-1",source_seq=2,
            checkpoint={"summary":"new turn arrived"},cursor={"last_turn":20})
        with pytest.raises(SessionCheckpointConflict,match="newer"):
            control.commit_chat_continuation(owner,transfer["continuation_id"],
                                             operator_approved=True)
        assert control.cancel_chat_continuation(owner,transfer["continuation_id"],
                         operator_approved=True)["state"]=="CANCELLED"
    finally:
        context.close();durable.close()


def test_reconcile_uncertain_after_core_committed(tmp_path):
    durable,context,control,owner,run,cp=setup_chat(tmp_path)
    try:
        transfer=control.prepare_chat_continuation(owner,run_id=run,chat_id="logical-chat",
            target_conversation_id="chatgpt-new",request_key="k1")
        control.session_checkpoints.transition_continuation(
            owner,transfer["continuation_id"],expected="PREPARED",state="REBINDING")
        durable.rebind_chat("logical-chat",owner,conversation_id="chatgpt-new",
                            conversation_url=None,expected_conversation_id="chatgpt-old")
        control.session_checkpoints.transition_continuation(
            owner,transfer["continuation_id"],expected="REBINDING",state="UNCERTAIN")
        assert control.reconcile_chat_continuation(owner,transfer["continuation_id"])["state"]=="COMMITTED"
    finally:
        context.close();durable.close()


def test_recovery_on_fresh_control_plane_instance(tmp_path):
    durable,context,control,owner,run,cp=setup_chat(tmp_path)
    transfer=control.prepare_chat_continuation(owner,run_id=run,chat_id="logical-chat",
            target_conversation_id="chatgpt-new",request_key="k1")
    control.session_checkpoints.transition_continuation(
        owner,transfer["continuation_id"],expected="PREPARED",state="REBINDING")
    durable.rebind_chat("logical-chat",owner,conversation_id="chatgpt-new",
                        conversation_url=None,expected_conversation_id="chatgpt-old")
    context.close();durable.close()
    restarted_durable,restarted_context,restarted=_services(tmp_path)
    try:
        status=restarted.reconcile_chat_continuation(owner,transfer["continuation_id"])
        assert status["state"]=="COMMITTED" and status["binding_matches_target"]
        assert restarted.commit_chat_continuation(owner,transfer["continuation_id"],
                                                  operator_approved=True)["idempotent_replay"]
    finally:
        restarted_context.close();restarted_durable.close()
