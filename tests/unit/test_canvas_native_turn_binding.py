"""The live actor creates one scoped journal turn; it is not a final receipt."""
import os
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentra_canvas.shell_actor import ShellActorService
from sentra_canvas.owned_process import TaskProcess
from sentra_canvas.store import Denied
from sentra_cli.canvas import CanvasBridge
from sentra_core.conversations import ConversationBusy, ConversationStore, _decode
from test_shell_actor_children import _dot, _prepare_parent_turn
from test_shell_dot_features import shell


@pytest.fixture(autouse=True)
def local_keyring(monkeypatch):
    if os.name != 'nt':
        values = {}
        monkeypatch.setitem(sys.modules, 'keyring', SimpleNamespace(
            set_password=lambda service, key, value: values.__setitem__((service, key), value),
            get_password=lambda service, key: values.get((service, key))))


@pytest.fixture
def setup(tmp_path):
    store = ConversationStore(tmp_path / 'state', principal='alice')
    ident = store.open(tmp_path)
    scope = {'owner':'canvas:alice', 'principal':'alice', 'workspace':str(tmp_path.resolve()),
             'project_id':'project', 'space_id':'space', 'conversation_id':ident,
             'run_id':'run', 'work_item_id':'work', 'agent_id':'agent', 'operation_id':'operation'}
    return store, ident, scope


def test_competing_reservations_produce_one_turn_and_never_retry(setup):
    store, ident, scope = setup
    def claim():
        try:
            return store.begin_canvas_turn(ident, 'original', scope)
        except ConversationBusy:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))
    winner = [result for result in results if result is not None]
    assert len(winner) == 1
    with store._connect() as db:
        rows = db.execute('SELECT * FROM canvas_native_turn_bindings').fetchall()
        assert len(rows) == 1 and rows[0]['turn_id'] == winner[0][0]
        assert _decode(rows[0]['protected_scope']) == scope
    assert [m['content'] for m in store.messages(ident)] == ['original']
    with pytest.raises(ConversationBusy):
        store.begin_canvas_turn(ident, 'different prompt', scope)


def test_scope_forgery_and_failed_insert_cannot_create_turn(setup):
    store, ident, scope = setup
    for key in ('owner', 'principal', 'workspace', 'conversation_id'):
        with pytest.raises((PermissionError, FileNotFoundError)):
            store.begin_canvas_turn(ident, 'prompt', {**scope, key:'foreign'})
    with store._tx() as db:
        db.execute("CREATE TRIGGER reject_native_binding BEFORE INSERT ON canvas_native_turn_bindings "
                   "BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.begin_canvas_turn(ident, 'prompt', scope)
    assert store.messages(ident) == []
    with store._connect() as db:
        assert db.execute('SELECT COUNT(*) FROM turns').fetchone()[0] == 0


def test_actor_derives_identity_and_rechecks_authority_after_reservation(setup, monkeypatch):
    store, ident, scope = setup
    message = {'project_id':'project', 'space_id':'space', 'conversation_id':ident,
               'run_id':'run', 'work_item_id':'work', 'operation_id':'operation', 'content':'host prompt'}
    dot = {'agent_id':'agent'}
    canvas = SimpleNamespace(store=SimpleNamespace(principal='alice'))
    actor = ShellActorService(SimpleNamespace(canvas=canvas, control=object(), owner='canvas:alice', conversations=store))
    calls = []
    def subject(token, payload):
        if token != 'valid':
            raise Denied('bad token')
        calls.append(token)
        return {'message':message, 'dot':dot}
    monkeypatch.setattr(actor, 'subject', subject)
    payload = {'action':'begin_native_turn', 'workspace':scope['workspace']}
    with pytest.raises(Denied): actor.dispatch('forged', payload)
    with pytest.raises(Denied): actor.dispatch('valid', {**payload, 'value':'forged prompt'})
    result = actor.dispatch('valid', payload)
    assert result['message']['content'] == 'host prompt'
    assert store.messages(ident) == [result['message']]
    with pytest.raises(ConversationBusy): actor.dispatch('valid', payload)
    assert len(calls) >= 3


def test_authority_revoked_during_reservation_interrupts_turn(setup, monkeypatch):
    store, ident, scope = setup
    message = {'project_id':'project', 'space_id':'space', 'conversation_id':ident,
               'run_id':'run', 'work_item_id':'work', 'operation_id':'operation', 'content':'prompt'}
    actor = ShellActorService(SimpleNamespace(canvas=SimpleNamespace(store=SimpleNamespace(principal='alice')),
        control=object(), owner='canvas:alice', conversations=store))
    calls = []
    def subject(token, payload):
        calls.append(token)
        if len(calls) == 2: raise Denied('revoked')
        return {'message':message, 'dot':{'agent_id':'agent'}}
    monkeypatch.setattr(actor, 'subject', subject)
    with pytest.raises(Denied):
        actor.dispatch('valid', {'action':'begin_native_turn', 'workspace':scope['workspace']})
    with store._connect() as db:
        assert db.execute('SELECT state FROM turns').fetchone()[0] == 'interrupted'
    with pytest.raises(ConversationBusy):
        store.begin_canvas_turn(ident, 'prompt', scope)


def test_cli_rejects_response_for_different_prompt(monkeypatch):
    monkeypatch.setenv('SENTRA_CANVAS_AGENT_TOKEN', 'x' * 40)
    monkeypatch.setenv('SENTRA_CANVAS_AGENT_PORT', '12345')
    monkeypatch.setenv('SENTRA_CANVAS_AGENT_SCOPE', 'shell')
    bridge = CanvasBridge(SimpleNamespace(workspace='workspace'))
    monkeypatch.setattr(bridge, '_request', lambda body: {'turn_id':'id', 'message':{'role':'user', 'content':'other'}})
    with pytest.raises(PermissionError): bridge.begin_native_turn('expected')


def test_live_actor_checks_token_and_protected_request(shell, monkeypatch):
    import time
    app, _, scope, call = shell
    monkeypatch.setattr(app._shell_runtime, '_execute', lambda _: None)
    root = _dot(call, 'BoundNative')
    conversation = call('conversation_create', dot_id=root['dot_id'])
    parent = _prepare_parent_turn(app, call, {**root, **scope}, conversation['conversation_id'])
    runtime = app._shell_runtime
    workspace = app.store.workspace(scope['project_id'])['path']
    runtime.conversations.open(workspace, session_id=conversation['conversation_id'])
    with runtime.control.store.connect('shell') as db:
        row = db.execute('SELECT protected_input FROM canvas_shell_queue WHERE operation_id=?',
                         (parent['operation_id'],)).fetchone()
    original = _decode(row[0])
    process = SimpleNamespace(poll=lambda:None)
    runtime._processes[parent['operation_id']] = process
    token = runtime.actors.register(original['message'], original['dot'], deadline=time.monotonic()+30)
    payload = {'action':'begin_native_turn', 'workspace':workspace}
    try:
        with pytest.raises(Denied): runtime.actors.dispatch('x'*48, payload)
        with pytest.raises(Denied): runtime.actors.dispatch(token, {**payload, 'workspace':'wrong'})
        result = runtime.actors.dispatch(token, payload)
        assert result['message']['content'] == original['message']['content']
        with pytest.raises(ConversationBusy): runtime.actors.dispatch(token, payload)
        runtime.actors.revoke(token)
        with pytest.raises(Denied): runtime.actors.dispatch(token, payload)
    finally:
        runtime._processes.pop(parent['operation_id'], None)
        runtime.actors.revoke(token)


def test_real_cli_process_and_http_actor_with_worktree(shell, monkeypatch, tmp_path):
    app, server, scope, call = shell
    monkeypatch.setattr(app._shell_runtime, '_execute', lambda _: None)
    root = _dot(call, 'NativeProcess')
    conversation = call('conversation_create', dot_id=root['dot_id'])
    parent = _prepare_parent_turn(app, call, {**root, **scope}, conversation['conversation_id'])
    runtime = app._shell_runtime
    project = Path(app.store.workspace(scope['project_id'])['path'])
    def git(*args):
        subprocess.run(['git', '-C', str(project), *args], check=True, capture_output=True,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    git('init'); git('config','user.name','Fixture'); git('config','user.email','fixture@localhost')
    (project / 'fixture.txt').write_text('base', encoding='utf-8')
    git('add','fixture.txt'); git('commit','-m','fixture')
    worktree = tmp_path / 'isolated-worktree'
    git('worktree','add','--detach',str(worktree))
    runtime.conversations.open(project, session_id=conversation['conversation_id'])
    with runtime.control.store.connect('shell') as db:
        row = db.execute('SELECT protected_input FROM canvas_shell_queue WHERE operation_id=?',
                         (parent['operation_id'],)).fetchone()
    original = _decode(row[0])
    baseline = runtime._native_journal_baseline(conversation['conversation_id'])
    # The CLI, journal and actor are real. Only model inference is a local fixture.
    marker, release = tmp_path / 'fixture-model-started', tmp_path / 'fixture-model-release'
    source = ("import getpass,os,sys,time,pathlib\n"
              "getpass.getuser=lambda:'local-owner'\n"
              "from sentra_cli.client import ModelClient\n"
              "def fixture(self,messages):\n"
              " pathlib.Path(os.environ['FIXTURE_MARKER']).write_text(os.getcwd())\n"
              " deadline=time.monotonic()+30\n"
              " while not pathlib.Path(os.environ['FIXTURE_RELEASE']).exists():\n"
              "  if time.monotonic()>deadline: raise TimeoutError('fixture release')\n"
              "  time.sleep(.05)\n"
              " yield 'fixture response'\n"
              "ModelClient.chat_stream=fixture\n"
              "from sentra_cli.__main__ import main\n"
              "sys.exit(main())\n")
    env = dict(os.environ)
    env.pop('SENTRA_CONTROL_BINDING_FILE', None)
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[2])
    env.update(FIXTURE_MARKER=str(marker), FIXTURE_RELEASE=str(release))
    process = None
    token = None
    try:
        with app._lock:
            token = runtime.actors.register(original['message'], original['dot'], deadline=time.monotonic()+60)
            env.update(SENTRA_CANVAS_AGENT_TOKEN=token, SENTRA_CANVAS_AGENT_PORT=str(server.server_port),
                       SENTRA_CANVAS_AGENT_SCOPE='shell')
            command = [sys.executable, '-c', source, '--prompt-stdin', '--workspace', str(project),
                       '--model', 'sentra/test-one', '--no-auto-start', '--state-dir', str(app.state_dir.parent),
                       '--resume', conversation['conversation_id']]
            process = TaskProcess(command, cwd=str(worktree), env=env, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            runtime._processes[parent['operation_id']] = process
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(process.communicate, input=original['message']['content'].encode(), timeout=60)
            try:
                deadline = time.monotonic()+30
                while not marker.exists() and time.monotonic()<deadline and not future.done():
                    time.sleep(.05)
                assert marker.exists(), 'CLI failed before reaching the local model fixture'
                assert Path(marker.read_text()).resolve() == worktree.resolve()
                with pytest.raises(ConversationBusy):
                    with runtime.conversations.lease(conversation['conversation_id']): pass
            finally:
                release.write_text('continue')
            output, _ = future.result(timeout=60)
        assert process.returncode == 0, output.decode('utf-8', errors='replace')
        with runtime.conversations._connect() as db:
            binding = db.execute('SELECT * FROM canvas_native_turn_bindings WHERE operation_id=?',
                                 (parent['operation_id'],)).fetchone()
            assert binding is not None
            assert db.execute('SELECT state FROM turns WHERE id=?', (binding['turn_id'],)).fetchone()[0] == 'completed'
        assert runtime.conversations.response_messages_for_turn(conversation['conversation_id'], binding['turn_id'])[-1]['content'] == 'fixture response'
        assert runtime._native_journal_final(original['message'], original['dot'], str(project), baseline)['content'] == 'fixture response'
    finally:
        if process is not None and process.poll() is None:
            process.terminate_tree(); process.communicate(timeout=10)
        runtime._processes.pop(parent['operation_id'], None)
        if token: runtime.actors.revoke(token)
