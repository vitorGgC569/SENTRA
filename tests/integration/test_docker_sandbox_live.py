"""Opt-in real containers, never silently substituted with mocks."""
import asyncio
import os

import pytest

from scripts.prepare_docker import SMOKE
from workspace.docker_runner import DockerClient, DockerCommandRunner

pytestmark = pytest.mark.skipif(os.environ.get('OMA_DOCKER_TESTS') != '1', reason='opt-in real Docker tests')


async def test_real_isolation_and_cleanup(tmp_path):
    (tmp_path/'probe.txt').write_text('source stays unchanged')
    (tmp_path/'.env').write_text('TEST_ONLY=not-a-real-secret')
    result = await DockerCommandRunner(tmp_path).run_argv(['python','-c',SMOKE],30)
    assert result['passed'], result
    assert result['cleanup_ok']
    assert (tmp_path/'probe.txt').read_text() == 'source stays unchanged'


async def test_real_timeout_removes_running_container(tmp_path):
    result = await DockerCommandRunner(tmp_path).run_argv(['python','-c','import time; time.sleep(90)'],2)
    assert not result['passed'] and result['cleanup_ok']
    remaining = await DockerClient().call(['ps','-aq','--filter','name='+result['container_name']])
    assert remaining['passed'] and not remaining['stdout'].strip()


async def test_real_cancel_removes_running_container(tmp_path):
    runner = DockerCommandRunner(tmp_path)
    names = []
    original = runner.create_args
    def args(name, snapshot, argv):
        names.append(name)
        return original(name,snapshot,argv)
    runner.create_args = args
    task = asyncio.create_task(runner.run_argv(['python','-c','import time; time.sleep(90)'],30))
    try:
        for _ in range(100):
            if names:
                state = await runner.client.call(['inspect','--format','{{.State.Running}}',names[0]])
                if state['passed'] and state['stdout'].strip() == 'true':
                    break
            await asyncio.sleep(.1)
        else:
            pytest.fail('container never started')
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    remaining = await runner.client.call(['ps','-aq','--filter','name='+names[0]])
    assert remaining['passed'] and not remaining['stdout'].strip()


async def test_operational_demo_and_promotion_stay_in_docker(tmp_path):
    from orchestrator.agents.router import ModelRouter
    from orchestrator.providers.mock_provider import MockProvider
    from orchestrator.runtime import IntegratedRun, promote_candidate
    (tmp_path/'math_utils.py').write_text('# baseline\n')
    provider = MockProvider()
    router = ModelRouter({'primary':provider,'master':provider},fallback_provider_name=None)
    result = await IntegratedRun(tmp_path,'docker-e2e','factorial',router,execution={'backend':'docker'}).run()
    assert result['status'] == 'CANDIDATE_READY'
    assert result['integration_tests']['verification_scope'] == 'docker_restricted_candidate'
    assert (tmp_path/'math_utils.py').read_text() == '# baseline\n'
    with pytest.raises(ValueError,match='same execution backend'):
        await promote_candidate(tmp_path,'docker-e2e',execution={'backend':'host'})
    with pytest.raises(ValueError,match='validation policy'):
        await promote_candidate(tmp_path,'docker-e2e',execution=result['execution'],commands=['[[LINT]]'])
    promoted = await promote_candidate(tmp_path,'docker-e2e',execution=result['execution'])
    assert promoted['status'] == 'APPLIED'
    import json
    evidence = json.loads((tmp_path/'runs'/'docker-e2e'/'promotion-tests.json').read_text())
    assert evidence['verification_scope'] == 'docker_restricted_candidate'
    assert all(item['execution_backend']=='docker' for item in evidence['results'])
