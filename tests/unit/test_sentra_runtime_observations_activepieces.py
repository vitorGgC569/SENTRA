"""Trusted effect-vs-observation classification for Activepieces recovery."""
from sentra_runtime.contracts import OperationRequest
from sentra_runtime.observations import is_observation


def req(cap, *, action="observe"):
    return OperationRequest(
        "op-a", "agent", "pieces-machine", cap, "work-a", "idem-a",
        {"action": action},
    )


def test_read_only_piece_observations_do_not_depend_on_agent_action_flags():
    readonly = (
        "activepieces:observe", "activepieces:artifact",
        "activepieces:catalog", "activepieces:trigger_reconcile",
    )
    for kind in ("pieces", "activepieces"):
        for cap in readonly:
            assert is_observation(req(cap, action="ignored"), kind) is True


def test_cancellation_trigger_and_piece_actions_are_always_effectful():
    mutation = (
        "activepieces:action", "activepieces:cancel", "activepieces:trigger_ingest",
        "activepieces:trigger_enable", "activepieces:trigger_disable",
        "activepieces:trigger_run", "activepieces:trigger_renew",
    )
    for kind in ("pieces", "activepieces"):
        for cap in mutation:
            assert is_observation(req(cap, action="observe"), kind) is False


def test_unknown_provider_or_capability_remains_unclassified():
    assert is_observation(req("activepieces:observe"), "untrusted-machine") is False
    assert is_observation(req("unrecognized:observe"), "pieces") is False
