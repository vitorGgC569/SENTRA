from types import SimpleNamespace
import pytest
from native_bridge.relay import RelayState


def fixture_state(*, send_fence=0, phase='ready', may_have_sent=False, job_state='FAILED', stage='QUEUED'):
    state = RelayState.__new__(RelayState)
    def original(job_id, worker, lease_token):
        if (job_id,worker,lease_token) != ('websend_own','TAB-1','original-lease'):
            raise PermissionError('foreign lease')
    state._original_worker=original
    state.web_send=SimpleNamespace(binding=lambda _: {'send_fence':send_fence,'stage':stage})
    state.pending_status=lambda _: {'state':job_state,'phase':phase,'may_have_sent':may_have_sent}
    return state


def test_failed_before_ack_releases_reference_but_never_requeues_or_grants_send():
    result=fixture_state().recovery_disposition(job_id='websend_own',worker='TAB-1',lease_token='original-lease')
    assert result == {'job_id':'websend_own','release_unsent_reference':True,'automatic_resend':False}


@pytest.mark.parametrize('change', [
    {'send_fence':1}, {'phase':'sending'}, {'phase':'sent'}, {'may_have_sent':True},
    {'job_state':'LEASED'}, {'job_state':'QUEUED'}, {'stage':'UNCONFIRMED'},
])
def test_any_possibility_of_send_retains_original_observation(change):
    result=fixture_state(**change).recovery_disposition(job_id='websend_own',worker='TAB-1',lease_token='original-lease')
    assert result['release_unsent_reference'] is False
    assert result['automatic_resend'] is False


def test_foreign_and_unleased_references_are_denied():
    for worker, token in [('TAB-2','original-lease'), ('TAB-1','foreign-lease'), ('','')]:
        with pytest.raises(PermissionError):
            fixture_state().recovery_disposition(job_id='websend_own',worker=worker,lease_token=token)
