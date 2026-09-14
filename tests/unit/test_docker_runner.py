import asyncio
import json
import sys

import pytest

from orchestrator.models import Candidate
from orchestrator.verification import CandidateVerifier
from workspace.command_runner import CommandRunner
from workspace.docker_runner import DockerClient, DockerCommandRunner, create_runner, settings

IMAGE = 'sha256:' + 'a'*64


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr('workspace.docker_runner.docker_executable', lambda: 'docker')
    calls = []

    async def prepare(self, image):
        calls.append(['prepare', image])
        return IMAGE

    async def call(self, args, timeout=20):
        calls.append(args)
        output = json.dumps({'Status': 'exited', 'ExitCode': 0, 'OOMKilled': False}) if args[0] == 'inspect' else 'ok'
        return CommandRunner._result(args, True, 0, stdout=output)

    monkeypatch.setattr(DockerClient, 'prepare', prepare)
    monkeypatch.setattr(DockerClient, 'call', call)
    return calls


def test_execution_configuration_is_fail_closed():
    with pytest.raises(ValueError):
        settings({'backend': 'shell'})
    with pytest.raises(ValueError):
        settings({'backend': 'docker', 'privileged': True})
    with pytest.raises(ValueError):
        settings({'backend': 'docker', 'image': '--privileged'})


async def test_only_filtered_readonly_snapshot_is_mounted(tmp_path, client):
    (tmp_path/'app.py').write_text('pass')
    (tmp_path/'.env').write_text('fake-secret')
    for private in ('.claude', '.docker'):
        (tmp_path/private).mkdir()
        (tmp_path/private/'config.json').write_text('private')
    original_call = DockerClient.call

    async def inspect_mount(self, args, timeout=20):
        if args[0] == 'create':
            from pathlib import Path
            mount = args[args.index('--mount')+1]
            snapshot = Path(mount.split('source=')[1].split(',target=')[0])
            assert snapshot != tmp_path
            assert {p.name for p in snapshot.iterdir()} == {'app.py'}
        return await original_call(self, args, timeout)

    runner = DockerCommandRunner(tmp_path, {'probe': ['python', '-c', 'print(1)']})
    runner.client.call = lambda args, timeout=20: inspect_mount(runner.client, args, timeout)
    result = await runner.run_command('[[TEST|probe]]')
    assert result['passed'] and result['cleanup_ok'] and result['image_id'] == IMAGE
    create = next(c for c in client if c[0] == 'create')
    for flag, value in {'--network':'none', '--cap-drop':'ALL', '--memory':'512m',
                         '--pids-limit':'64', '--user':'65532:65532', '--pull':'never'}.items():
        assert create[create.index(flag)+1] == value
    assert '--read-only' in create and 'readonly' in create[create.index('--mount')+1]
    assert create.index(IMAGE) < create.index('print(1)')
    assert client[-1] == ['rm', '--force', result['container_name']]
    assert (tmp_path/'app.py').read_text() == 'pass'


def test_default_commands_map_python_and_candidate_paths(tmp_path, client):
    (tmp_path/'tests').mkdir()
    runner = create_runner(tmp_path, execution={'backend':'docker'})
    assert runner.resolve_command('[[TEST|all]]') == ['python','-m','pytest','-q','--','/workspace/tests']
    assert runner.resolve_command('[[LINT]]')[0:3] == ['python', '-I', '-c']
    with pytest.raises(ValueError):
        runner.resolve_command('echo unsafe')


async def test_missing_docker_never_runs_candidate_on_host(tmp_path, client, monkeypatch):
    async def unavailable(self, image):
        raise ValueError('daemon is down')
    monkeypatch.setattr(DockerClient, 'prepare', unavailable)
    runner = DockerCommandRunner(tmp_path, {'probe':['python','-c','raise RuntimeError()']})
    result = await runner.run_command('[[TEST|probe]]')
    assert not result['passed'] and 'SANDBOX_BLOCKED' in result['stderr']
    assert client == []


@pytest.mark.parametrize('cancel', [False, True])
async def test_timeout_and_cancel_remove_exact_container(tmp_path, client, monkeypatch, cancel):
    original = DockerClient.call
    async def call(self, args, timeout=20):
        if args[0] == 'start':
            if cancel:
                raise asyncio.CancelledError()
            return CommandRunner._result(args, False, -1, stderr='timed out')
        return await original(self, args, timeout)
    monkeypatch.setattr(DockerClient, 'call', call)
    runner = DockerCommandRunner(tmp_path, {'probe':['python','-c','pass']})
    if cancel:
        with pytest.raises(asyncio.CancelledError):
            await runner.run_command('[[TEST|probe]]', 1)
    else:
        assert not (await runner.run_command('[[TEST|probe]]', 1))['passed']
    create = next(c for c in client if c[0] == 'create')
    assert client[-1] == ['rm','--force',create[create.index('--name')+1]]


async def test_cleanup_failure_blocks_success(tmp_path, client, monkeypatch):
    original = DockerClient.call
    async def call(self, args, timeout=20):
        if args[0] == 'rm':
            return CommandRunner._result(args, False, -1)
        return await original(self, args, timeout)
    monkeypatch.setattr(DockerClient, 'call', call)
    result = await DockerCommandRunner(tmp_path).run_argv(['python','-c','pass'])
    assert not result['passed'] and not result['cleanup_ok']


async def test_verifier_records_container_evidence(tmp_path, client):
    (tmp_path/'tests').mkdir()
    (tmp_path/'tests'/'test_app.py').write_text('def test_app(): assert True')
    evidence = await CandidateVerifier(tmp_path, execution={'backend':'docker'}).verify(Candidate(task_id='T'))
    assert evidence['all_passed'] and evidence['source_unchanged']
    assert evidence['verification_scope'] == 'docker_restricted_candidate'
    assert evidence['results'][0]['image_id'] == IMAGE


async def test_gateway_executes_through_selected_backend(tmp_path, client):
    from repository.gateway import CommandGateway
    gateway = CommandGateway(tmp_path, execution={'backend':'docker'}, profiles={'probe':['python','-c','pass']})
    session = gateway.open_session()
    output = await gateway.execute(session, '[[TEST|probe]]')
    assert 'PASS' in output and any(c[0]=='create' for c in client)


async def test_model_cannot_change_fixed_test_harness(tmp_path, client):
    candidate = Candidate(task_id='T', patch='--- /dev/null\n+++ b/tests/test_cheat.py\n@@ -0,0 +1 @@\n+pass\n')
    evidence = await CandidateVerifier(tmp_path, execution={'backend':'docker'},
                                       allowed_patch_paths=['app.py']).verify(candidate)
    assert not evidence['all_passed']
    assert 'PATCH_SCOPE_DENIED' in evidence['results'][0]['stderr']
    assert client == []
