"""Central lease foundation only; this does not certify unwired input transports."""
import pytest

from sentra_canvas.terminal_possession import TerminalPossession
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_runtime.executor import AuthorizationRequired


@pytest.fixture
def authority(tmp_path):
    control = ControlPlaneService.from_store(tmp_path, backend='sqlite')
    now = [1000.0]
    value = TerminalPossession(control, 'owner-a', clock=lambda: now[0])
    resource = value.resource('project', 'terminal', 'a' * 32, 'runtime')
    try:yield value, resource, now
    finally:
        control.context.close()
        control.durable.close()


def test_two_authority_instances_share_exclusive_client_and_epoch(authority):
    owner, resource, now = authority
    other = TerminalPossession(owner.control, owner.owner, clock=lambda: now[0])
    lease = owner.acquire(resource, 'desktop:origin-a')
    with pytest.raises(AuthorizationRequired):other.acquire(resource, 'mobile:device-b')
    moved = other.acquire(resource, 'mobile:device-b', takeover=True, expected_epoch=lease['epoch'])
    assert moved['epoch'] > lease['epoch']
    with pytest.raises(ValueError):owner.release(resource, 'desktop:origin-a', lease['epoch'])
    assert owner.status(resource)['client_id'] == 'mobile:device-b'


@pytest.mark.parametrize('error', [TimeoutError, KeyboardInterrupt])
def test_possible_write_stays_uncertain_and_same_proof_cannot_repeat(authority, error):
    owner, resource, _ = authority
    data = 'one 🦊\r'.encode()
    proof = owner.prepare(resource, 'desktop:a', 'request-key', data)
    effects = []
    with pytest.raises(error):
        with owner.physical(proof, data):
            effects.append(data)
            raise error('lost write confirmation')
    result = owner.inspect(proof)
    assert result['state'] == 'uncertain' and result['may_resend'] is False
    with pytest.raises(AuthorizationRequired):
        with owner.physical(proof, data):effects.append(data)
    assert effects == [data]
    with pytest.raises(AuthorizationRequired):owner.prepare(resource, 'desktop:a', 'new-key', b'new\r')


def test_delivered_receipt_is_not_task_completion_or_reusable_proof(authority):
    owner, resource, _ = authority
    proof = owner.prepare(resource, 'desktop:a', 'one', b'once\r')
    with owner.physical(proof, b'once\r'):pass
    result = owner.inspect(proof)
    assert result['resolved'] and result['receipt']['stage'] == 'delivered_to_process'
    assert result['receipt']['task_completion_verified'] is False
    with pytest.raises(AuthorizationRequired):
        with owner.physical(proof, b'once\r'):pytest.fail('effect repeated')
    with pytest.raises(AuthorizationRequired):owner.prepare(resource, 'desktop:a', 'one', b'once\r')


def test_expired_possession_blocks_physical_write(authority):
    owner, resource, now = authority
    proof = owner.prepare(resource, 'desktop:a', 'one', b'one')
    now[0] += 31
    with pytest.raises(AuthorizationRequired):
        with owner.physical(proof, b'one'):pytest.fail('expired input delivered')


def test_changed_payload_or_owner_cannot_use_reserved_physical_identity(authority):
    owner, resource, now = authority
    proof = owner.prepare(resource, 'desktop:a', 'one', b'one')
    with pytest.raises(AuthorizationRequired):
        with owner.physical(proof, b'other'):pytest.fail('changed bytes delivered')
    other = TerminalPossession(owner.control, 'owner-b', clock=lambda: now[0])
    with pytest.raises(AuthorizationRequired):other.inspect(proof)
    with pytest.raises(AuthorizationRequired):other.acquire(resource, 'desktop:b')
    assert owner.inspect(proof)['state'] == 'prepared'
