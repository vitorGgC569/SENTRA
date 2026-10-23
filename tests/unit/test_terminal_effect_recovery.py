"""Protected host observation/CAS; daemon evidence here is synthetic."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
from threading import Event

import pytest

from test_shell_request_retention import host, acknowledge
from sentra_canvas.shell_requests import HostRequestCapacityError
from sentra_mcp.services.shell_coordinator import ShellConflict


def identity():
    payload = {'terminal_id':'terminal-a','input_target':'a' * 32,'data':'private command\r'}
    fp = hashlib.sha256(json.dumps(['terminal_input',payload],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    reference = {'effect_key':'host-input:' + 'b' * 64,'workspace_id':'project-a','terminal_id':'terminal-a',
                 'runtime_id':'c' * 32,'generation':'d' * 32,
                 'payload_sha256':hashlib.sha256(payload['data'].encode()).hexdigest()}
    receipt = {**reference,'input_receipt_protocol_version':1,'stage':'delivered_to_process','automatic_retry':False,'task_completion_verified':False}
    return payload,fp,reference,receipt


def test_exact_observation_can_ack_retire_and_deduplicate_without_command_replay(host):
    payload,fp,reference,receipt = identity()
    key = 'recover-input-key'
    def lost():
        host.note_before_admission('project-a',key)
        host.bind_terminal_input_effect('project-a',key,fp,reference)
        host.note_effect_possible('project-a',key)
        raise TimeoutError('possible effect, missing transport reply')
    with pytest.raises(TimeoutError):host.invoke('project-a','terminal_input',payload,key,lost)
    assert not host.inspect('project-a','terminal_input',payload,key)['resolved']
    assert host.intent('project-a',key,fp)['terminal_effect'] == reference
    assert host.confirm_terminal_input_observation('project-a',key,fp,reference,receipt)
    value = host.inspect('project-a','terminal_input',payload,key)
    assert value['resolved'] and value['result']['observed'] and not value['result']['task_completion_verified']
    assert acknowledge(host,key,fp)
    assert host.compact_acknowledged('project-a')['retired'] == 1
    duplicate = host.invoke('project-a','terminal_input',payload,key,lambda:pytest.fail('replayed command'))
    assert duplicate['payload_retired'] and duplicate['delivery_stage'] == 'delivered_to_process'
    assert 'terminal_effect' not in host.intent('project-a',key,fp)


@pytest.mark.parametrize('retire_before_callback',[False,True])
@pytest.mark.parametrize('late_failure',[False,True])
def test_observed_delivery_fences_a_late_callback(host,retire_before_callback,late_failure):
    payload,fp,reference,receipt = identity()
    key = 'racing-input-key'
    waiting,release = Event(),Event()
    def delayed_failure():
        host.note_before_admission('project-a',key)
        host.bind_terminal_input_effect('project-a',key,fp,reference)
        host.note_effect_possible('project-a',key)
        waiting.set()
        assert release.wait(5)
        if late_failure:raise TimeoutError('late reply failure after daemon delivery was observed')
        return {'status':'delivered','late_callback':True}
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(host.invoke,'project-a','terminal_input',payload,key,delayed_failure)
        try:
            assert waiting.wait(5)
            assert host.confirm_terminal_input_observation('project-a',key,fp,reference,receipt)
            if retire_before_callback:
                assert acknowledge(host,key,fp)
                assert host.compact_acknowledged('project-a')['retired'] == 1
        finally:release.set()
        if late_failure:
            with pytest.raises(TimeoutError):future.result(timeout=5)
        else:assert future.result(timeout=5)['late_callback']
    value = host.inspect('project-a','terminal_input',payload,key)
    assert value['resolved'] and value['journal_state'] == 'observed_input'
    if retire_before_callback:
        assert value['result']['payload_retired'] and 'physical_receipt' not in value['result']
    else:assert value['result']['physical_receipt'] == receipt


@pytest.mark.parametrize('change', [{'runtime_id':'e' * 32}, {'generation':'e' * 32},
    {'payload_sha256':'e' * 64}, {'stage':'task_completed'}, {'automatic_retry':True}])
def test_mismatched_receipt_cannot_resolve_uncertainty(host, change):
    payload,fp,reference,receipt = identity()
    key = 'mismatched-input'
    def lost():
        host.note_before_admission('project-a',key)
        host.bind_terminal_input_effect('project-a',key,fp,reference)
        host.note_effect_possible('project-a',key)
        raise TimeoutError()
    with pytest.raises(TimeoutError):host.invoke('project-a','terminal_input',payload,key,lost)
    with pytest.raises(ShellConflict):host.confirm_terminal_input_observation('project-a',key,fp,reference,{**receipt,**change})
    assert not host.inspect('project-a','terminal_input',payload,key)['resolved']


def test_physical_selector_growth_is_charged_before_admission(host):
    payload,fp,reference,_ = identity()
    key = 'capacity-input-key'
    def denied():
        host.note_before_admission('project-a',key)
        usage = host.retention_status()
        host.retention_policy = replace(host.retention_policy,
            max_protected_bytes=usage['protected_bytes'] + usage['reserved_bytes'])
        host.bind_terminal_input_effect('project-a',key,fp,reference)
        pytest.fail('input was admitted without selector budget')
    with pytest.raises(HostRequestCapacityError):host.invoke('project-a','terminal_input',payload,key,denied)
    assert 'terminal_effect' not in host.intent('project-a',key,fp)
    value = host.inspect('project-a','terminal_input',payload,key)
    assert value['resolved'] and value['result']['status'] == 'admission_failed'
