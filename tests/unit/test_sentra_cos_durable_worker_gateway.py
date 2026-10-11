"""Actual patched Worker -> actual Gateway private endpoints -> central SQLite.

Account/rollout attestations and provider DOM are synthetic. The original Edge
variant retains its assistant fixture. Electron variant uses default message/
assistant callbacks against actual temporary Host HTTP and committed reader;
its WebContents bridge reads isolated Chromium. Never account/build approval.
"""
import json
import os
from pathlib import Path
import subprocess
from threading import Thread
from urllib.request import Request, urlopen

import pytest

from sentra_model_gateway.gateway import GatewayConfig, GatewayServer
from sentra_model_gateway.web_transport import DurableWebTransport
from test_web_turn_authority import descriptor


@pytest.mark.parametrize('collector_kind', ['edge', 'electron', 'electron-authchanged'])
def test_worker_private_handshake_receipt_answer_existing_run(tmp_path, collector_kind):
    root = Path(__file__).resolve().parents[2]
    tree = os.environ.get('SENTRA_BROWSER_QA_TREE')
    if not tree:
        pytest.skip('Set SENTRA_BROWSER_QA_TREE to a reproducibly patched disposable tree')
    electron = collector_kind != 'edge'
    account_changed = collector_kind == 'electron-authchanged'
    path = tmp_path / 'browser.json'
    gateway = GatewayServer(GatewayConfig(port=0, state_root=tmp_path / 'state', browser_descriptor=path))
    authority = gateway.turn_authority
    owner = 'canvas:worker-gateway-qa'
    document = dict(document_id='a' * 32, identity_epoch='b' * 32, surface_id='surface-one')
    proof = {**document, 'extension_id': 'a' * 32, 'source_sha256': 'b' * 64,
        'worker': 'TAB-713', 'browser_principal': owner, 'account_verified': True,
        'approval_state': 'idle', 'selection_verified': True, 'requested_model': 'chatgpt-web/gpt-6',
        'requested_effort': 'high', 'model': 'gpt-6', 'effort': 'high'}
    if electron:
        # Explicit account fixture, not promotion of the uncalibrated collector.
        proof.update(collector_kind='electron', authentication_revision=1,
                     extension_id='sentra-committed-account-menu-v1', worker='electron-worker-qa')
    callbacks = {} if electron else {
        'assistant_attestor': lambda **expected: {**expected, 'authenticated': True}}
    transport = DurableWebTransport(authority, account_attestor=lambda *args: proof,
        activation_validator=lambda mode: True, **callbacks)
    gateway._web_transport = transport
    control = transport.control
    run = authority.durable.create_run(owner, workspace=str(tmp_path))['run_id']
    authority.durable.transition_run(run, owner, 'RUNNING')
    control.ensure_agent(run, owner, agent_id='worker-qa', role='builder')
    item = control.create_work_item(run, owner, objective='Isolated actual Worker QA', assignee_agent_id='worker-qa')
    grant = control.authorization.grant(owner, principal_type='agent', principal_id='worker-qa', capability='web:send',
        scope_type='work_item', scope_id=item['work_item_id'])
    transport.bind('conversation://worker-qa', owner=owner, run_id=run, work_item_id=item['work_item_id'],
        principal_id='worker-qa', grant_id=grant['grant_id'])
    transport.set_mode('durable_v2', expected_revision=0)
    payload = {'model': 'chatgpt-web/gpt-6', 'reasoning': {'effort': 'high'}, 'input': 'Original Responses fixture'}
    capability = transport.admit_responses(conversation_uri='conversation://worker-qa', request_identity='worker-qa-request', payload=payload)
    descriptor(path, trace='trace-fixture')
    if electron:
        control.browser_evidence.configure_host(collector_id=proof['extension_id'], source_sha256=proof['source_sha256'],
            principal=owner, workspace=str(tmp_path), surface_id=document['surface_id'], worker=proof['worker'],
            enabled=True, expected_revision=0)
    else:
        control.browser_evidence.configure(extension_id=proof['extension_id'], source_sha256=proof['source_sha256'],
            principal=owner, workspace=str(tmp_path), enabled=True, expected_revision=0)
    thread = Thread(target=gateway.serve_forever, daemon=True)
    thread.start()
    config = { 'tree': tree, 'chromium': os.environ.get('SENTRA_QA_CHROMIUM') or str(Path(os.environ['LOCALAPPDATA']) / 'ms-playwright/chromium-1234/chrome-win64/chrome.exe'),
        'endpoint': f'http://127.0.0.1:{gateway.server_port}', 'token': gateway.turn_authority_token,
        'identity': document, 'capability': capability, 'prompt': 'Actual transformed physical prompt, isolated fixture only',
        'independent_host': electron, 'browser_descriptor_path': str(path),
        'host_authentication_revision': 2 if account_changed else 1}
    private_config = tmp_path / 'worker-private-config.json'
    private_config.write_text(json.dumps(config), encoding='utf-8')
    try:
        if collector_kind == 'edge':
            request = Request(config['endpoint'] + '/internal/turn/browser-start',
                data=json.dumps({'capability': capability, 'traceId': 'trace-fixture'}).encode(),
                headers={'Authorization': 'Bearer ' + gateway.turn_authority_token, 'Content-Type': 'application/json'})
            with urlopen(request, timeout=10) as result:
                assert result.status == 200
        process = subprocess.run([str(root / '.sentra/toolchain/node_modules/bun/bin/bun.exe'),
            'run', str(root / 'tests/unit/sentra_cos_durable_gateway_runner.ts')],
            env={**os.environ, 'SENTRA_GATEWAY_QA_CONFIG': str(private_config)}, capture_output=True,
            text=True, timeout=60, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if account_changed:
            # Exact user role/body/IDs do not overcome a different Host account
            # epoch. Receipt is denied after one physical Send; no replay/final.
            assert process.returncode != 0
            assert 'SENTRA_WORKER_GATEWAY_QA_ANSWERED' not in process.stdout
            # Private producer deliberately hides backend error details; verify
            # authority rejection and central state rather than leaked reason.
            assert 'sentra_receipt_rejected:' in process.stderr
            with pytest.raises(PermissionError):
                transport.require_receipts(capability)
            status = transport.delivery_view(capability)['messages'][0]
            assert status['state'] not in {'SENT', 'ANSWERING', 'ANSWERED'}
            assert status['send_fence'] == 1
            assert transport.jobs.counts()['submitted'] == 1
            assert len(authority.durable.list_runs(owner)['items']) == 1
            assert len(authority.durable.list_operations(run, owner)['items']) == 1
            return
        assert process.returncode == 0, process.stdout + process.stderr
        assert 'SENTRA_WORKER_GATEWAY_QA_ANSWERED' in process.stdout
        if electron:
            assert 'SENTRA_WORKER_GATEWAY_HOST_QA_ANSWERED' in process.stdout
            assert authority._capability(capability).browser_account_revision == 1
        transport.require_receipts(capability)
        status = transport.delivery_view(capability)['messages'][0]
        assert status['state'] == 'ANSWERED'
        assert status['answer_message_id'] == 'assistant-fixture'
        assert status['answer_revision'] == 2
        assert status['send_fence'] == 1
        assert transport.jobs.counts()['submitted'] == 1
        assert len(authority.durable.list_runs(owner)['items']) == 1
        assert len(authority.durable.list_operations(run, owner)['items']) == 1
        database = tmp_path / 'state/browser/relay.sqlite3'
        assert config['prompt'].encode() not in database.read_bytes()
    finally:
        private_config.unlink(missing_ok=True)
        gateway.shutdown()
        gateway.server_close()
        thread.join(timeout=3)
