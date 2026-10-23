"""Recover central input possession from exact existing daemon receipts only.

Most cases use a synthetic PTY with real protected SQLite and daemon logic.
The explicit Windows case starts its own real ConPTY daemon. Neither scope
qualifies fully wired desktop/mobile arbitration or an installed package.
"""
from concurrent.futures import ThreadPoolExecutor
import copy
import os
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from sentra_canvas.terminal_possession import TerminalPossession,observe_terminal_input
from sentra_canvas.pty_client import DaemonPTY
from sentra_canvas.pty_daemon import PtyHost
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_runtime.executor import AuthorizationRequired
from test_pty_input_effects import FakePTY


@pytest.fixture
def recovery(tmp_path):
    control=ControlPlaneService.from_store(tmp_path/'central',backend='sqlite')
    authority=TerminalPossession(control,'owner')
    host=PtyHost(tmp_path/'daemon',factory=FakePTY)
    calls=[]
    def call(method,fields=None,key=None):
        calls.append(method);return host.dispatch(method,fields or {},key)
    client=SimpleNamespace(capabilities=host.dispatch('health',{})['capabilities'],call=call)
    terminal=DaemonPTY.create(client,'project','terminal',['synthetic'],tmp_path)
    resource=authority.resource('project','terminal',terminal.input_generation,terminal.runtime_id)
    data='one 🪐\r'.encode()
    proof=authority.prepare(resource,'desktop:one','request:one',data)
    reference=terminal.input_reference(proof['effect_key'],data)
    def lose_confirmation():
        with pytest.raises(TimeoutError):
            with authority.physical(proof,data):
                terminal.write_correlated(data,reference)
                raise TimeoutError('physical daemon reply deliberately lost')
    yield SimpleNamespace(authority=authority,control=control,host=host,terminal=terminal,
        client=client,calls=calls,resource=resource,data=data,proof=proof,reference=reference,
        lose_confirmation=lose_confirmation)
    host.close();control.context.close();control.durable.close()


def test_lost_confirmation_unblocks_future_input_only_after_exact_read_receipt(recovery):
    r=recovery;r.authority.bind_reference(r.proof,r.reference);r.lose_confirmation()
    assert r.authority.inspect(r.proof)['state']=='uncertain'
    with pytest.raises(AuthorizationRequired):r.authority.prepare(r.resource,'desktop:one','request:two',b'new')
    restored=TerminalPossession(r.control,'owner')
    r.calls.clear()
    canvas=SimpleNamespace(_terminal_possession=restored,_lock=threading.RLock(),_pty_client=r.client)
    observed=observe_terminal_input(canvas,r.proof)
    assert observed['resolved'] and observed['state']=='delivered'
    assert observed['receipt']['recovered_by_observation'] is True
    assert observed['receipt']['task_completion_verified'] is False and observed['may_resend'] is False
    assert r.calls==['input_effect']
    assert r.host.sessions['terminal']['pty'].writes==[r.data]
    with pytest.raises(AuthorizationRequired):
        with restored.physical(r.proof,r.data):pytest.fail('reconciliation repeated physical input')
    following=restored.prepare(r.resource,'desktop:one','request:two',b'new')
    assert following['epoch']==r.proof['epoch']


def test_reference_is_protected_exact_and_cannot_be_invented_after_effect(recovery):
    r=recovery
    r.authority.bind_reference(r.proof,r.reference)
    assert r.authority.daemon_reference(r.proof)==r.reference
    with r.control.store.connect('machine_input_control') as db:
        value=db.execute('SELECT protected_reference FROM terminal_physical_input_refs').fetchone()[0]
    assert value.startswith(('dpapi:','keyring:')) and r.proof['effect_key'] not in value
    r.lose_confirmation()
    assert r.authority.bind_reference(r.proof,r.reference)==r.reference
    # A historical reservation without pre-effect correlation stays uncertain.
    with r.control.store.connect('machine_input_control') as db,db:
        db.execute('DELETE FROM terminal_physical_input_refs')
    with pytest.raises(AuthorizationRequired):r.authority.bind_reference(r.proof,r.reference)
    assert r.authority.inspect(r.proof)['state']=='uncertain'


@pytest.mark.parametrize('field',['effect_key','workspace_id','terminal_id','runtime_id','generation','payload_sha256'])
def test_another_daemon_selector_cannot_bind_to_this_reservation(recovery,field):
    r=recovery;changed={**r.reference,field:'b'*(64 if field=='payload_sha256' else 32)}
    with pytest.raises((AuthorizationRequired,ValueError)):r.authority.bind_reference(r.proof,changed)
    assert r.authority.daemon_reference(r.proof) is None


@pytest.mark.parametrize('mutation',[
    {'resolved':False},{'found':False},{'state':'uncertain'},{'automatic_retry':True},
    {'may_resend':True},{'task_completion_verified':True},{'input_receipt_protocol_version':True},
    {'receipt':{'stage':'completed'}},
])
def test_partial_or_overstated_daemon_evidence_never_promotes_uncertainty(recovery,mutation):
    r=recovery;r.authority.bind_reference(r.proof,r.reference);r.lose_confirmation()
    observed=r.client.call('input_effect',r.reference)
    observed.update(mutation)
    with pytest.raises(AuthorizationRequired):r.authority.confirm_daemon_observation(r.proof,observed)
    assert r.authority.inspect(r.proof)['state']=='uncertain'
    assert r.host.sessions['terminal']['pty'].writes==[r.data]


@pytest.mark.parametrize('field',['effect_key','workspace_id','terminal_id','runtime_id','generation','payload_sha256'])
def test_delivered_receipt_from_another_exact_scope_is_not_evidence(recovery,field):
    r=recovery;r.authority.bind_reference(r.proof,r.reference);r.lose_confirmation()
    observed=r.client.call('input_effect',r.reference)
    observed['receipt'][field]='b'*(64 if field=='payload_sha256' else 32)
    with pytest.raises(AuthorizationRequired):r.authority.confirm_daemon_observation(r.proof,observed)
    assert r.authority.inspect(r.proof)['state']=='uncertain'


def test_missing_daemon_or_unknown_reference_never_starts_or_replays_a_process(recovery):
    r=recovery;r.authority.bind_reference(r.proof,r.reference)
    canvas=SimpleNamespace(_terminal_possession=r.authority,_lock=threading.RLock())
    result=observe_terminal_input(canvas,r.proof)
    assert result['observation_available'] is False and not result['resolved']
    canvas._pty_client=r.client;r.calls.clear()
    result=observe_terminal_input(canvas,r.proof)
    assert result['observation_available'] is True and not result['resolved']
    assert r.calls==['input_effect'] and r.host.sessions['terminal']['pty'].writes==[]


def test_concurrent_observers_adopt_one_receipt_without_changing_possession(recovery):
    r=recovery;r.authority.bind_reference(r.proof,r.reference);r.lose_confirmation()
    before=r.authority.status(r.resource)
    observed=r.client.call('input_effect',r.reference)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:r.authority.confirm_daemon_observation(r.proof,copy.deepcopy(observed)),range(8)))
    assert all(value['resolved'] for value in results)
    assert r.authority.status(r.resource)==before
    assert r.host.sessions['terminal']['pty'].writes==[r.data]


def test_historical_receipt_after_daemon_restart_never_respawns_a_terminal(recovery,tmp_path):
    r=recovery;r.authority.bind_reference(r.proof,r.reference);r.lose_confirmation()
    r.host.close()
    restored=PtyHost(tmp_path/'daemon',factory=lambda *a,**k:pytest.fail('observation spawned a terminal'))
    try:
        assert restored.runtime_id!=r.reference['runtime_id']
        observed=restored.dispatch('input_effect',r.reference)
        assert r.authority.confirm_daemon_observation(r.proof,observed)['resolved']
        assert restored.dispatch('inventory',{})==[]
    finally:restored.close()


def test_observation_does_not_renew_an_expired_lease(recovery):
    r=recovery;r.authority.bind_reference(r.proof,r.reference);r.lose_confirmation()
    r.authority.clock=lambda:time.time()+61
    before=r.authority.status(r.resource)
    assert before['live'] is False
    observed=r.client.call('input_effect',r.reference)
    assert r.authority.confirm_daemon_observation(r.proof,observed)['resolved']
    assert r.authority.status(r.resource)==before


@pytest.mark.skipif(os.name!='nt',reason='real Windows ConPTY, isolated owned daemon')
def test_real_daemon_recovers_possession_after_lost_reply_without_repeating_input(tmp_path,monkeypatch):
    from sentra_canvas.pty_client import PtyDaemonClient
    daemon_state=tmp_path/'daemon';daemon_state.mkdir()
    process=subprocess.Popen([sys.executable,'-m','sentra_canvas.pty_daemon',str(daemon_state)],
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW)
    terminal=None;control=None
    try:
        client=None
        for _ in range(70):
            if process.poll() is not None:pytest.fail('owned daemon exited before readiness')
            try:client=PtyDaemonClient(daemon_state);break
            except (OSError,ValueError,KeyError,RuntimeError):time.sleep(.1)
        assert client is not None
        terminal=DaemonPTY.create(client,'workspace','terminal',['cmd.exe','/d','/q'],tmp_path)
        control=ControlPlaneService.from_store(tmp_path/'central',backend='sqlite')
        authority=TerminalPossession(control,'owner')
        resource=authority.resource('workspace','terminal',terminal.input_generation,terminal.runtime_id)
        data=b'<nul set /p =once >> effect.txt & echo POSSESSION_RECOVERY_OK\r'
        proof=authority.prepare(resource,'desktop:first','physical-request-once',data)
        reference=terminal.input_reference(proof['effect_key'],data)
        authority.bind_reference(proof,reference)
        real_call=client.call
        def lost_response(method,fields=None,key=None):
            result=real_call(method,fields,key)
            if method=='write_correlated':raise TimeoutError('real daemon completed; confirmation deliberately lost')
            return result
        monkeypatch.setattr(client,'call',lost_response)
        with pytest.raises(TimeoutError):
            with authority.physical(proof,data):terminal.write_correlated(data,reference)
        assert authority.inspect(proof)['state']=='uncertain'
        for _ in range(70):
            if (tmp_path/'effect.txt').exists() and (tmp_path/'effect.txt').read_text().strip()=='once':break
            time.sleep(.1)
        assert (tmp_path/'effect.txt').read_text().strip()=='once'
        pid=terminal.pid
        restored=TerminalPossession(control,'owner')
        reconnected=PtyDaemonClient(daemon_state)
        calls=[];read=reconnected.call
        def observation_only(method,fields=None,key=None):
            assert method=='input_effect';calls.append(method);return read(method,fields,key)
        monkeypatch.setattr(reconnected,'call',observation_only)
        canvas=SimpleNamespace(_terminal_possession=restored,_lock=threading.RLock(),_pty_client=reconnected)
        result=observe_terminal_input(canvas,proof)
        assert result['resolved'] and result['receipt']['recovered_by_observation'] is True
        assert calls==['input_effect']
        with pytest.raises(AuthorizationRequired):
            with restored.physical(proof,data):pytest.fail('old proof attempted a second write')
        # A second origin requires an explicit owner handoff; observation alone
        # never changes the client, epoch or authority.
        with pytest.raises(AuthorizationRequired):restored.acquire(resource,'mobile:second')
        handed=restored.acquire(resource,'mobile:second',expected_epoch=proof['epoch'],takeover=True)
        assert handed['epoch']>proof['epoch']
        assert (tmp_path/'effect.txt').read_text().strip()=='once'
        assert terminal.pid==pid and terminal.poll() is None
        monkeypatch.setattr(client,'call',real_call)
        terminal.close();terminal=None
        client.call('drain');client.call('stop_when_idle');process.wait(timeout=8)
        assert process.returncode==0
    finally:
        if terminal:
            try:terminal.close()
            except Exception:pass
        if process.poll() is None:process.terminate();process.wait(timeout=10)
        if control:control.context.close();control.durable.close()
