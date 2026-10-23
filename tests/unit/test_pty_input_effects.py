"""Exact daemon receipts without command replay; synthetic PTYs unless specified."""
import base64
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from http.server import BaseHTTPRequestHandler
from threading import Event, Thread
from types import SimpleNamespace
import urllib.request

import pytest

from sentra_canvas.pty_client import DaemonPTY
from sentra_canvas.pty_daemon import PtyHost, PtyServer, UncertainPTY
from sentra_canvas.pty_input_effects import validate_reference
from sentra_canvas.terminal import TerminalError


class FakePTY:
    pid = 12345
    def __init__(self, *args, **kwargs):
        self.writes = []
        self.failure = None
        self.code = None
    def write(self, data):
        self.writes.append(data)
        if self.failure:raise self.failure('confirmation lost after possible write')
    def poll(self):return self.code
    def close(self, **kwargs):self.code = 0
    def wait_output(self, timeout):return True


@pytest.fixture
def runtime(tmp_path):
    host = PtyHost(tmp_path, factory=FakePTY)
    client = SimpleNamespace(capabilities=host.dispatch('health', {})['capabilities'],
                             call=lambda method, fields=None, key=None:host.dispatch(method, fields or {}, key))
    terminal = DaemonPTY.create(client, 'project', 'terminal', ['synthetic'], tmp_path)
    try:yield host, terminal
    finally:host.close()


def test_unknown_receipt_observation_does_not_reserve_or_write(runtime):
    host, terminal = runtime
    reference = terminal.input_reference('request:unknown', b'one\r')
    for _ in range(3):
        value = host.dispatch('input_effect', reference)
        assert not value['found'] and not value['resolved'] and not value['may_resend']
    assert host.db.execute('SELECT COUNT(*) FROM input_effect_refs').fetchone()[0] == 0
    assert host.sessions['terminal']['pty'].writes == []


def test_exact_receipt_deduplicates_and_survives_new_daemon_without_respawn(runtime, tmp_path):
    host, terminal = runtime
    data = 'one 🦊\r'.encode()
    reference = terminal.input_reference('request:one', data)
    result = terminal.write_correlated(data, reference)
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(value == result for value in pool.map(lambda _:terminal.write_correlated(data, reference), range(12)))
    assert host.sessions['terminal']['pty'].writes == [data]
    observed = host.dispatch('input_effect', reference)
    assert observed['resolved'] and observed['receipt']['stage'] == 'delivered_to_process'
    assert observed['task_completion_verified'] is False and observed['automatic_retry'] is False
    assert host.dispatch('inventory', {})[0]['input_generation'] == terminal.input_generation
    host.close()
    restored = PtyHost(tmp_path, factory=lambda *a, **k:pytest.fail('observation respawned a PTY'))
    try:
        assert restored.runtime_id != reference['runtime_id']
        assert restored.dispatch('input_effect', reference) == observed
        assert restored.dispatch('inventory', {}) == []
    finally:restored.close()


@pytest.mark.parametrize('field', ['workspace_id', 'terminal_id', 'runtime_id', 'generation', 'payload_sha256'])
def test_receipt_rejects_another_scope_even_when_key_exists(runtime, field):
    host, terminal = runtime
    reference = terminal.input_reference('request:bound', b'one')
    terminal.write_correlated(b'one', reference)
    changed = {**reference, field:'b' * (64 if field == 'payload_sha256' else 32)}
    with pytest.raises(PermissionError, match='exact scope'):host.dispatch('input_effect', changed)
    assert host.sessions['terminal']['pty'].writes == [b'one']


@pytest.mark.parametrize('failure', [TimeoutError, KeyboardInterrupt])
def test_uncertain_physical_write_is_observable_and_never_repeated(runtime, failure):
    host, terminal = runtime
    reference = terminal.input_reference('request:uncertain', b'possible')
    host.sessions['terminal']['pty'].failure = failure
    with pytest.raises(failure):terminal.write_correlated(b'possible', reference)
    observed = host.dispatch('input_effect', reference)
    assert observed['found'] and not observed['resolved'] and observed['state'] == 'uncertain'
    with pytest.raises(UncertainPTY):terminal.write_correlated(b'possible', reference)
    assert host.sessions['terminal']['pty'].writes == [b'possible']


def test_changed_data_or_generation_cannot_write(runtime):
    host, terminal = runtime
    reference = terminal.input_reference('request:changed', b'one')
    with pytest.raises(ValueError):terminal.write_correlated(b'other', reference)
    changed = {**reference,'generation':'a' * 32}
    with pytest.raises(TerminalError):terminal.write_correlated(b'one', changed)
    fields = {**changed,'data':base64.b64encode(b'one').decode()}
    with pytest.raises(PermissionError):host.dispatch('write_correlated', fields, changed['effect_key'])
    assert host.db.execute('SELECT COUNT(*) FROM input_effect_refs').fetchone()[0] == 0
    assert host.sessions['terminal']['pty'].writes == []


def test_legacy_host_lacks_capability_and_never_gets_fallback_input(runtime):
    host, terminal = runtime
    terminal.client.capabilities = {}
    with pytest.raises(TerminalError, match='no fallback'):terminal.input_reference('request:old', b'one')
    assert host.sessions['terminal']['pty'].writes == []


def test_capacity_refuses_new_input_but_keeps_existing_receipt_observable(runtime, monkeypatch):
    import sentra_canvas.pty_daemon as daemon
    host, terminal = runtime
    first = terminal.input_reference('request:first', b'one')
    terminal.write_correlated(b'one', first)
    monkeypatch.setattr(daemon,'MAX_INPUT_EFFECTS',1)
    second = terminal.input_reference('request:second', b'two')
    with pytest.raises(ValueError,match='capacity'):terminal.write_correlated(b'two',second)
    assert host.dispatch('input_effect',first)['resolved']
    assert not host.dispatch('input_effect',second)['found']
    assert host.sessions['terminal']['pty'].writes == [b'one']


def test_failed_reservation_rolls_back_its_reference_before_any_write(runtime):
    host, terminal = runtime
    reference = terminal.input_reference('request:rollback',b'one')
    host.db.execute("CREATE TRIGGER reservation_failure BEFORE INSERT ON effects WHEN NEW.key='request:rollback' "
                    "BEGIN SELECT RAISE(ABORT,'injected reservation failure'); END")
    host.db.commit()
    with pytest.raises(sqlite3.IntegrityError,match='reservation failure'):
        terminal.write_correlated(b'one',reference)
    assert not host.dispatch('input_effect',reference)['found']
    assert host.db.execute('SELECT COUNT(*) FROM input_effect_refs').fetchone()[0] == 0
    assert host.sessions['terminal']['pty'].writes == []


def test_old_inflight_receipt_is_uncertain_after_restart_and_never_respawns(runtime,tmp_path):
    host, terminal = runtime
    reference = terminal.input_reference('request:inflight',b'one')
    terminal.write_correlated(b'one',reference)
    # Model process loss between the committed possible-effect boundary and
    # receipt commit. This cannot establish whether a physical write occurred.
    host.db.execute("UPDATE effects SET state='in_flight',result=NULL WHERE key=?",(reference['effect_key'],))
    host.db.commit();host.close()
    restored = PtyHost(tmp_path,factory=lambda *a,**k:pytest.fail('recreated an uncertain process'))
    try:
        observed = restored.dispatch('input_effect',reference)
        assert observed['found'] and observed['state']=='uncertain' and not observed['resolved']
        with pytest.raises(UncertainPTY):restored.dispatch('write_correlated',
            {**reference,'data':base64.b64encode(b'one').decode()},reference['effect_key'])
        assert restored.dispatch('inventory',{}) == []
    finally:restored.close()


@pytest.mark.parametrize('extra', [{'data':'private command'}, {'principal':'owner'}, {'generation':None}])
def test_selector_refuses_payload_and_unversioned_identity(runtime, extra):
    _, terminal = runtime
    reference = terminal.input_reference('request:selector', b'one')
    with pytest.raises(ValueError):validate_reference({**reference, **extra})


def test_receipt_journal_contains_digest_and_no_command_bytes(runtime):
    host, terminal = runtime
    data = b'unique-private-command-that-is-not-journal-metadata\r'
    reference = terminal.input_reference('request:private', data)
    terminal.write_correlated(data, reference)
    assert reference['payload_sha256'] == hashlib.sha256(data).hexdigest()
    rows = host.db.execute('SELECT r.reference,e.result FROM input_effect_refs r JOIN effects e ON r.key=e.key').fetchall()
    assert data.decode() not in json.dumps(rows)
    assert 'unique-private-command' not in json.dumps(rows)


def test_daemon_server_drains_accepted_reader_before_closing_its_database(runtime):
    host, terminal = runtime
    reference = terminal.input_reference('request:drain-reader', b'one')
    entered,release,listener_stopped = Event(),Event(),Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):pass
        def do_GET(self):
            entered.set()
            assert release.wait(5)
            value = host.dispatch('input_effect', reference)
            assert not value['found']
            self.send_response(200);self.send_header('Content-Length','2');self.end_headers()
            self.wfile.write(b'ok')
    server = PtyServer(('127.0.0.1',0), Handler)
    serving = Thread(target=server.serve_forever,daemon=True)
    serving.start()
    def read():
        with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/',timeout=6) as response:
            return response.read()
    def stop():
        server.shutdown()
        listener_stopped.set()
        server.server_close()
        host.close()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            reading = pool.submit(read)
            assert entered.wait(3)
            stopping = pool.submit(stop)
            try:
                assert listener_stopped.wait(3)
                with pytest.raises(FutureTimeout):stopping.result(timeout=.1)
                assert not host._closed
            finally:release.set()
            assert reading.result(timeout=3) == b'ok'
            stopping.result(timeout=3)
            assert host._closed
    finally:
        release.set();server.shutdown();server.server_close();serving.join(3)
