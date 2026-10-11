"""Production React -> actual Canvas HTTP -> existing central SQLite. No real Web.

Only the temporary Vite process, Chromium context and CanvasServer created here
are stopped. API routing relays unchanged to the real authenticated server.
"""
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from test_sentra_cos_canvas_ux_browser import vite
from test_sentra_runtime_canvas_center_http import running_canvas, request as canvas_request


def test_real_react_goal_and_uncertain_delivery_use_central_authority(tmp_path, vite):
    from playwright.sync_api import sync_playwright, expect
    from native_bridge.job_store import JobStore
    from native_bridge.web_send import WebSendAuthority

    with running_canvas(tmp_path) as (app, server):
        ws = app.create_workspace('Durable-browser-QA')['id']
        runtime = app._runtime()
        run = runtime.run(ws)
        runtime.durable.transition_run(run['run_id'], runtime.owner, 'RUNNING')
        control = app._machine_service().control
        control.ensure_agent(run['run_id'], runtime.owner, agent_id='browser-qa', role='builder')
        item = control.create_work_item(run['run_id'], runtime.owner, objective='Isolated delivery QA', assignee_agent_id='browser-qa')
        grant = control.authorization.grant(runtime.owner, principal_type='agent', principal_id='browser-qa',
            capability='web:send', scope_type='work_item', scope_id=item['work_item_id'])
        runtime.durable.bind_chat(run['run_id'], runtime.owner, agent_id='browser-qa', provider='chatgpt',
            conversation_id='conversation-fixture', chat_id='logical-chat-qa')
        operation = runtime.durable.create_operation(run['run_id'], runtime.owner, kind='chatgpt-web-turn', initial_state='RUNNING', idempotency_key='isolated-canvas-qa')
        outbox = app.state_dir.parent / 'browser/relay.sqlite3'
        outbox.parent.mkdir(parents=True, exist_ok=True)
        jobs = JobStore(outbox)
        web = WebSendAuthority(control, jobs)
        job = web.admit(runtime.owner, request_identity='isolated-delivery-qa', run_id=run['run_id'],
            operation_id=operation['operation_id'], work_item_id=item['work_item_id'], principal_id='browser-qa',
            grant_id=grant['grant_id'], workspace=run['workspace'], conversation_key='conversation://isolated-canvas-qa',
            prompt='Private synthetic test only', requested_model='gpt-6', requested_effort='high', target_worker='TAB-QA')
        claim = web.claim(runtime.owner, job['job_id'], worker='TAB-QA')
        lease = runtime.durable.acquire_lease(run['run_id'], runtime.owner, 'browser-tab:TAB-QA', operation_id=operation['operation_id'], ttl_s=120)
        web.pre_send(runtime.owner, job['job_id'], worker='TAB-QA', lease_token=claim['lease_token'],
            resource_key=lease['resource_key'], fencing_token=lease['fencing_token'])
        web.failure(runtime.owner, job['job_id'], reason='Synthetic post-fence lost observation')
        assert web.status(runtime.owner, job['job_id'])['state'] == 'UNCONFIRMED'
        calls = []
        def relay(route):
            request = route.request
            assert request.headers.get('authorization') == 'Bearer ' + server.secret
            path = '/' + request.url.split('/', 3)[3]
            calls.append((request.method, path, request.post_data_json if request.post_data else None))
            wire = Request(f'http://127.0.0.1:{server.server_port}' + path,
                data=request.post_data.encode() if request.post_data else None,
                headers={'Authorization': 'Bearer ' + server.secret, 'Content-Type': 'application/json'}, method=request.method)
            try:
                with urlopen(wire, timeout=10) as response:
                    route.fulfill(status=response.status, content_type='application/json', body=response.read())
            except HTTPError as response:
                route.fulfill(status=response.code, content_type='application/json', body=response.read())
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(viewport={'width': 1280, 'height': 950})
                context.add_init_script('window.__QA_WORKSPACE_ID=' + json.dumps(ws))
                page = context.new_page()
                page.route('**/api/center/**', relay)
                page.goto(vite + '/desktop-assets/src/qa/durable-web-test.html#token=' + server.secret)
                expect(page.get_by_role('dialog', name='Entrega Web e objetivos')).to_be_visible()
                expect(page.get_by_text('Entrega não confirmada', exact=True)).to_be_visible()
                expect(page.get_by_role('button', name='Reenviar')).to_have_count(0)
                page.get_by_label('Objetivo', exact=True).fill('Objetivo protegido da QA local')
                page.get_by_role('button', name='Salvar objetivo').click()
                expect(page.get_by_role('region', name='Objetivo persistido')).to_be_visible()
                expect(page.get_by_role('region', name='Objetivo persistido').get_by_text('Objetivo protegido da QA local', exact=True)).to_be_visible()
                page.get_by_label('Custo máximo (USD)').fill('0')
                page.get_by_role('button', name='Iniciar Loop com estes limites').click()
                expect(page.get_by_role('alert')).to_contain_text('Ação bloqueada:')
                page.get_by_role('button', name='Interromper objetivo / Loop').click()
                expect(page.get_by_text('CANCELLED', exact=False)).to_be_visible()
                page.get_by_role('button', name='Atualizar estado').click()
                expect(page.get_by_text('Entrega não confirmada', exact=True)).to_be_visible()
                assert web.status(runtime.owner, job['job_id'])['send_fence'] == 1
                assert jobs.counts()['submitted'] == 1
                mutations = [body for method, _, body in calls if method == 'POST']
                assert [body['action'] for body in mutations] == ['set', 'start', 'stop']
                assert all('operator_approved' not in body for body in mutations)
                compact = page.get_by_role('region', name='Compactar e retomar')
                compact.get_by_label('Chat ID existente', exact=True).fill('logical-chat-qa')
                compact.get_by_label('WorkItem ID existente', exact=True).fill(item['work_item_id'])
                compact.get_by_label('Agente / principal existente', exact=True).fill('browser-qa')
                compact.get_by_label('Chave estável deste pedido', exact=True).fill('compact-qa-request')
                compact.get_by_label('Resumo para o sucessor', exact=True).fill('Resumo revisado apenas para QA local')
                expect(compact.get_by_role('button', name='Preparar Compact&Resume')).to_be_disabled()
                compact.get_by_text('Inspecionar o resumo antes de preparar', exact=True).click()
                expect(compact.locator('pre')).to_have_text('Resumo revisado apenas para QA local')
                compact.get_by_label('Revisei o resumo e os bindings existentes').check()
                compact.get_by_role('button', name='Preparar Compact&Resume').click()
                expect(compact.get_by_text('BLOCKED', exact=True)).to_be_visible()
                expect(compact.get_by_text('Sucessor não confirmado.', exact=True)).to_be_visible()
                expect(compact.get_by_role('button', name='Retomar sucessor confirmado')).to_be_disabled()
                assert jobs.counts()['submitted'] == 1  # only original uncertain job, no successor Send
                compact_calls = [body for method, path, body in calls if method == 'POST' and 'compact-resume' in path]
                assert len(compact_calls) == 1
                assert compact_calls[0]['arguments']['summary'] == 'Resumo revisado apenas para QA local'
                assert 'operator_approved' not in compact_calls[0]['arguments']
                # Seed an existing transfer with the real central authority in this
                # disposable server. It queues context only; no worker is started.
                from native_bridge.continuation_web import WebContinuation
                allocated = WebContinuation(control, jobs).allocate_new_target(runtime.owner,
                    run_id=run['run_id'], chat_id='logical-chat-qa', work_item_id=item['work_item_id'],
                    principal_id='browser-qa', request_key='allocation-qa-existing',
                    summary='Resumo revisado apenas para QA local', operator_approved=True)
                compact.get_by_label('Identificador existente', exact=True).fill(allocated['allocation_id'])
                compact.get_by_role('button', name='Consultar Compact&Resume').click()
                expect(compact.get_by_text('WAITING_RECEIPT', exact=True)).to_be_visible()
                expect(compact.get_by_role('button', name='Retomar sucessor confirmado')).to_be_disabled()
                code, denied = canvas_request(server, '/api/center/compact-resume', json_body={
                    'ws': ws, 'action': 'resume', 'arguments': {'allocation_id': allocated['allocation_id']}})
                assert code == 200 and denied['state'] == 'BLOCKED' and denied['successor_ready'] is False
                assert jobs.counts()['submitted'] == 2
                context.close()
                browser.close()
        finally:
            jobs.close()
