"""Production React + bridge + real controlled HTTP, with synthetic turns only."""
from __future__ import annotations
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import subprocess
import threading
import time
import urllib.request
from playwright.sync_api import sync_playwright, Error as PlaywrightError

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / 'sentra_canvas' / 'desktop_ui'
PROJECT, SPACE, DOT = 'qa-turn', 'qa-space', 'qa-dot'
TOKEN = 'synthetic-qa-only-bearer'


class Backend:
    def __init__(self, *, lost_creation=False, restored=False, delay_home=False, paginated=False, selected_in_home=False):
        self.lock = threading.RLock()
        self.requests, self.conversations, self.messages = [], [], []
        self.creation_requests = {}
        self.lost_creation = lost_creation
        self.paginated, self.emit_event = paginated, False
        self.selected_in_home, self.lookup_state = selected_in_home, None
        self.release_home = threading.Event()
        if not delay_home:
            self.release_home.set()
        self.dot = {'project_id': PROJECT, 'space_id': SPACE, 'dot_id': DOT, 'agent_id': 'qa-agent',
                    'name': 'Astra QA', 'role': 'specialist', 'model': 'sentra/test-one', 'status': 'idle'}
        self.space = {'project_id': PROJECT, 'space_id': SPACE, 'name': 'QA de envio'}
        if paginated:
            self.conversations.extend(self.conversation('old-' + str(index)) for index in range(60))
        if restored:
            self.conversations.append(self.conversation('existing'))
            self.messages.append({'project_id': PROJECT, 'space_id': SPACE, 'conversation_id': 'existing',
                'message_id': 'canonical-restored', 'request_key': 'qa-restored-request-key', 'role': 'user', 'content': 'Envio antigo sintético',
                'status': 'queued', 'operation_id': 'qa-restored-operation', 'created_at': '2026-01-01T00:00:00Z'})

    def conversation(self, identifier):
        return {'project_id': PROJECT, 'space_id': SPACE, 'dot_id': DOT, 'conversation_id': identifier,
                'title': 'Conversa de teste sintético', 'status': 'active', 'updated_at': '2026-01-01T00:00:00Z'}

    def home(self, project=PROJECT):
        if project == 'qa-second':
            space = {**self.space, 'project_id': project, 'space_id': 'qa-second-space', 'name': 'Outro projeto QA'}
            dot = {**self.dot, 'project_id': project, 'space_id': 'qa-second-space', 'dot_id': 'qa-second-dot', 'name': 'Outro Dot QA'}
            return {'project_id': project, 'space': space, 'spaces': [space], 'dots': [dot], 'conversations': [],
                'teams': [], 'documents': [], 'capabilities': [], 'run': {'state': 'RUNNING'}, 'activity': {'items': [], 'cursor': 0}}
        visible = self.conversations[:50] if self.paginated else self.conversations
        if self.selected_in_home and self.conversations:
            visible = [self.conversations[-1], *self.conversations[:49]]
        return {'project_id': PROJECT, 'space': self.space, 'spaces': [self.space], 'dots': [self.dot],
                'conversations': list(visible), 'teams': [], 'documents': [], 'capabilities': [],
                'run': {'state': 'RUNNING', 'run_id': 'qa-run'}, 'activity': {'items': [], 'cursor': 0}}

    def bridge(self, body):
        action = body.get('action')
        if action == 'home':
            self.release_home.wait(timeout=20)
        with self.lock:
            self.requests.append({'action': action, 'request_key': body.get('request_key'),
                                  'conversation_id': body.get('conversation_id'), 'project_id': body.get('project_id'), 'keys': sorted(body)})
            if action == 'home':
                return self.home(body.get('project_id')), False
            if body.get('project_id') == 'qa-second':
                data = self.home('qa-second')
                if action == 'space_get':
                    return {**data['space'], 'dots': data['dots'], 'conversations': [], 'teams': [], 'documents': []}, False
                if action in {'dot_list', 'space_list', 'conversation_list'}:
                    return {'items': data[{'dot_list': 'dots', 'space_list': 'spaces', 'conversation_list': 'conversations'}[action]], 'page': {'total': 1, 'next_offset': None}}, False
                return {'items': [], 'cursor': 0}, False
            if action == 'space_get':
                return {**self.space, 'dots': [self.dot], 'conversations': list(self.conversations[:50] if self.paginated else self.conversations), 'teams': [], 'documents': []}, False
            if action in {'dot_list', 'space_list', 'conversation_list', 'message_list'}:
                values = {'dot_list': [self.dot], 'space_list': [self.space], 'conversation_list': self.conversations, 'message_list': self.messages}[action]
                if action == 'message_list':
                    values = [row for row in values if row['conversation_id'] == body['conversation_id']]
                total = len(values)
                offset, limit = body.get('offset', 0), body.get('limit', 50)
                values = values[offset:offset+limit]
                return {'items': list(values), 'page': {'total': total, 'next_offset': offset+limit if offset+limit < total else None}}, False
            if action == 'conversation_create':
                row = self.creation_requests.get(body['request_key'])
                if row is None:
                    row = self.conversation('created-' + str(len(self.conversations) + 1))
                    self.creation_requests[body['request_key']] = row
                    self.conversations.append(row)
                drop = self.lost_creation
                self.lost_creation = False
                return row, drop
            if action == 'conversation_request_status':
                row = self.creation_requests.get(body['request_key'])
                return {'status': 'confirmed' if row else 'unconfirmed', 'confirmed': bool(row), 'conversation': row}, False
            if action == 'conversation_get':
                row = next((row for row in self.conversations if row['conversation_id'] == body['conversation_id'] and row['space_id'] == body['space_id'] and row['project_id'] == body['project_id']), None)
                if row is None:
                    raise ValueError('Canonical conversation absent')
                return dict(row), False
            if action == 'message_request_status':
                row = next((row for row in self.messages if row.get('request_key') == body['request_key'] and row['conversation_id'] == body['conversation_id'] and row['role'] == 'user'), None)
                if self.lookup_state:
                    return {'status': self.lookup_state, 'confirmed': False, 'found': self.lookup_state != 'unverified',
                        'automatic_retry': False, 'request_key': body['request_key']}, False
                return {'status': 'confirmed' if row else 'unverified', 'confirmed': bool(row), 'found': bool(row),
                    'automatic_retry': False, 'request_key': body['request_key'], 'message': row}, False
            if action == 'message_send':
                existing = next((row for row in self.messages if row.get('request_key') == body['request_key']), None)
                if existing:
                    return existing, False
                user = {'project_id': PROJECT, 'space_id': SPACE, 'conversation_id': body['conversation_id'],
                        'message_id': 'sent-' + body['request_key'], 'request_key': body['request_key'], 'role': 'user',
                        'content': body['content'], 'status': 'queued', 'operation_id': 'qa-operation-' + str(len(self.messages)),
                        'receipt_id': 'qa-synthetic-receipt', 'created_at': '2026-01-01T00:01:00Z'}
                self.messages.append(user)
                self.messages.append({**user, 'message_id': 'answer-' + body['request_key'], 'request_key': None,
                    'role': 'assistant', 'content': 'Turno sintético recebido pelo HTTP de QA.', 'status': 'succeeded', 'created_at': '2026-01-01T00:01:01Z'})
                return user, False
            if action == 'access_status':
                return {'mode': 'ask', 'requests': []}, False
            if action == 'events' and self.emit_event:
                self.emit_event = False
                return {'items': [{'event_id': 'qa-refresh-event', 'kind': 'conversation.updated', 'seq': 1}], 'cursor': 1, 'has_more': False}, False
            return {'items': [], 'cursor': 0, 'has_more': False}, False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        if self.headers.get('Authorization') != 'Bearer ' + TOKEN:
            self.send_error(401)
            return
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))))
        value, drop = self.server.backend.bridge(body)
        if drop:
            self.close_connection = True
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        payload = json.dumps({'ok': True, 'value': value}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def control_state(page):
    return page.evaluate('''() => {
      const input=document.querySelector('.shell-composer textarea');
      const send=document.querySelector('.shell-composer button[type=submit]');
      const parents=[]; for(let node=input; node; node=node.parentElement) if(node.inert||node.hasAttribute('inert')) parents.push({tag:node.tagName,id:node.id,inert:node.inert,attribute:node.getAttribute('inert')});
      const drafts=Object.keys(sessionStorage).filter(key=>key.startsWith('sentra_shell_draft:')).map(key=>{const value=JSON.parse(sessionStorage.getItem(key));return {key,pending_request_key:value.pending?.request_key||null};});
      return {textarea_present:Boolean(input),textarea_disabled:input?.disabled,send_disabled:send?.disabled,ancestors_inert:parents,drafts,
        main_inert:document.querySelector('#shell-main-focus')?.inert,main_inert_attribute:document.querySelector('#shell-main-focus')?.getAttribute('inert')};
    }''')


def main():
    scenarios = ('immediate', 'lost_creation', 'restored_draft', 'warm_cache', 'paginated_create', 'outside_first_page', 'selected_in_home', 'pending_missing', 'pending_uncertain', 'pending_rejected', 'native_bridge', 'project_switch')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', action='append', choices=scenarios)
    args = parser.parse_args()
    selected = args.scenario or scenarios
    output = ROOT / '.tmp' / ('astra-chat-turn-qa' + ('-' + '-'.join(selected) if args.scenario else ''))
    output.mkdir(parents=True, exist_ok=True)
    with socket.socket() as candidate:
        candidate.bind(('127.0.0.1', 0)); port = candidate.getsockname()[1]
    log = (output / 'vite.log').open('w', encoding='utf-8')
    vite = subprocess.Popen(['node', 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', str(port), '--strictPort'], cwd=UI, stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    endpoint = f'http://127.0.0.1:{port}/desktop-assets/qa/chat-turn.html'
    report = {'synthetic_only': True, 'model_inference': False, 'production_shell_and_bridge': True, 'scenarios': {}, 'failures': []}
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(endpoint, timeout=1).close(); break
            except OSError:
                if vite.poll() is not None: raise RuntimeError('Vite exited')
                time.sleep(.1)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for name in selected:
                pending_unconfirmed = name.startswith('pending_')
                backend = Backend(lost_creation=name == 'lost_creation', restored=name in {'restored_draft', 'warm_cache', 'outside_first_page'} or pending_unconfirmed, delay_home=name == 'warm_cache', paginated=name in {'paginated_create', 'outside_first_page', 'selected_in_home'}, selected_in_home=name == 'selected_in_home')
                if pending_unconfirmed:
                    backend.lookup_state = {'pending_missing': 'unverified', 'pending_uncertain': 'uncertain', 'pending_rejected': 'rejected'}[name]
                    backend.messages.clear()
                server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
                server.backend = backend
                worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
                context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                errors, console_errors, states = [], [], {}
                start_chat = name in {'restored_draft', 'warm_cache', 'outside_first_page'} or pending_unconfirmed
                navigation = {'view': 'chat' if start_chat else 'dots', 'project_id': PROJECT, 'space_id': SPACE,
                    'dot_id': DOT if start_chat else None, 'conversation_id': 'existing' if start_chat else None}
                init = {'sentra_native_token': TOKEN, 'sentra_shell_theme': 'light', 'sentra_shell_navigation': json.dumps(navigation)}
                if name == 'restored_draft' or pending_unconfirmed:
                    init['sentra_shell_draft:' + PROJECT + ':existing'] = json.dumps({'content': '', 'pending': {'action': 'message_send', 'project_id': PROJECT, 'space_id': SPACE, 'conversation_id': 'existing', 'request_key': 'qa-restored-request-key', 'content': 'Envio antigo sintético'}})
                if name == 'warm_cache':
                    init['sentra_visual_home_v1:' + PROJECT] = json.dumps({'version': 1, 'at': int(time.time()*1000), 'home': backend.home()})
                context.add_init_script('const initial=' + json.dumps(init) + '; for(const [key,value] of Object.entries(initial)){(key.includes("navigation")||key.includes("theme")?localStorage:sessionStorage).setItem(key,value);}')
                context.add_init_script('window.qaPendingFlashes=0; new MutationObserver(()=>{if(document.querySelector(".shell-pending-operations"))window.qaPendingFlashes++;}).observe(document,{subtree:true,childList:true});')
                if name == 'native_bridge':
                    context.add_init_script('window.qaNativeCalls=[]; window.pywebview={api:{check_update_notification:async()=>({available:false}),reauthorize:async()=>{window.qaNativeCalls.push("reauthorize");return {authenticated_owner:true};},minimize:()=>window.qaNativeCalls.push("minimize")}};')
                if name == 'project_switch':
                    context.add_init_script('const originalFetch=window.fetch.bind(window);window.fetch=async(...args)=>{const response=await originalFetch(...args);let payload;try{payload=JSON.parse(args[1]?.body||"{}")}catch{}if(payload?.action==="conversation_create")await new Promise(resolve=>window.qaReleaseCreate=resolve);return response;};')
                def route_api(route):
                    if route.request.url.split('?')[0].endswith('/api/shell/bridge'):
                        try:
                            response = route.fetch(url=f'http://127.0.0.1:{server.server_port}/api/shell/bridge', timeout=25000)
                            route.fulfill(response=response)
                        except PlaywrightError:
                            route.abort('failed')
                    else:
                        route.fulfill(status=404 if '/api/shell/stream' in route.request.url else 200, content_type='application/json', body=json.dumps({'status': 'idle', 'content': '', 'items': []}))
                context.route('**/api/**', route_api)
                context.route('**/sentra-logo.png', lambda route: route.fulfill(path=str(ROOT / 'sentra_canvas/static/sentra-logo.png')))
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('console', lambda message: console_errors.append(message.text) if message.type == 'error' else None)
                try:
                    page.goto(endpoint)
                    if name == 'warm_cache':
                        page.locator('.shell-warm-indicator').wait_for()
                        states['cached_before_home'] = control_state(page)
                        if not states['cached_before_home']['main_inert']:
                            report['failures'].append('warm_cache: cached ancestor is not inert before authoritative home')
                        backend.release_home.set()
                        page.locator('.shell-warm-indicator').wait_for(state='detached')
                    else:
                        page.locator('.shell-main[inert]').wait_for(state='detached')
                    if name in {'immediate', 'lost_creation', 'paginated_create', 'selected_in_home', 'native_bridge', 'project_switch'}:
                        page.locator('.shell-dot-card footer button').filter(has_text='Conversar').click()
                        if name == 'project_switch':
                            page.wait_for_function('typeof window.qaReleaseCreate === "function"')
                            page.locator('.shell-project-label select').select_option('qa-second')
                            page.locator('.shell-dot-card h3').filter(has_text='Outro Dot QA').wait_for()
                            page.evaluate('window.qaReleaseCreate()')
                            page.wait_for_timeout(300)
                            assert json.loads(page.evaluate('localStorage.getItem("sentra_shell_navigation")'))['project_id'] == 'qa-second'
                            assert page.locator('.shell-chat-host:not([hidden]) .shell-composer').count() == 0
                            assert not page.locator('.shell-dot-card footer button').filter(has_text='Conversar').is_disabled()
                            assert page.locator('.shell-pending-operations').count() == 0
                            assert len([row for row in backend.requests if row['action'] == 'conversation_create']) == 1
                            states['after_switch_and_old_response'] = control_state(page)
                            page.screenshot(path=str(output / (name + '-1440.png')), full_page=True)
                            continue
                        if name == 'lost_creation':
                            consult = page.get_by_role('button', name='Consultar criação', exact=True)
                            consult.wait_for(); page.wait_for_function('!Array.from(document.querySelectorAll("button")).find(node=>node.textContent==="Consultar criação")?.disabled')
                            states['lost_response_before_consult'] = control_state(page)
                            consult.click()
                        page.locator('.shell-chat-heading').wait_for()
                    if name in {'paginated_create', 'selected_in_home'}:
                        states['created_before_refresh'] = control_state(page)
                        backend.emit_event = True
                        page.wait_for_timeout(5200)
                        states['after_paginated_refresh'] = control_state(page)
                        assert states['after_paginated_refresh']['textarea_present'], 'Confirmed conversation disappeared after the first page replaced the collection'
                    if name == 'outside_first_page':
                        page.wait_for_timeout(1200)
                        states['selected_outside_page'] = control_state(page)
                        assert states['selected_outside_page']['textarea_present'], 'Selected canonical conversation outside first page never resolves'
                    page.locator('.shell-composer textarea').wait_for()
                    if pending_unconfirmed:
                        page.get_by_role('button', name='Consultar envio', exact=True).click()
                        page.get_by_text('Nenhuma mensagem foi reenviada.', exact=False).first.wait_for()
                        page.wait_for_function('!Array.from(document.querySelectorAll("button")).find(node=>node.textContent==="Consultar envio")?.disabled')
                        states['after_read_only_consult'] = control_state(page)
                        assert states['after_read_only_consult']['textarea_disabled'] is True
                        assert states['after_read_only_consult']['drafts'][0]['pending_request_key'] == 'qa-restored-request-key'
                        assert not any(row['action'] == 'message_send' for row in backend.requests)
                        checks = [row for row in backend.requests if row['action'] == 'message_request_status']
                        assert len(checks) == 1 and checks[0]['request_key'] == 'qa-restored-request-key'
                        assert checks[0]['keys'] == ['action', 'conversation_id', 'project_id', 'request_key', 'space_id']
                        page.screenshot(path=str(output / (name + '-1440.png')), full_page=True)
                        continue
                    page.wait_for_function('document.querySelector(".shell-composer textarea")?.disabled === false')
                    states['ready'] = control_state(page)
                    assert not states['ready']['ancestors_inert'], states['ready']
                    assert page.get_by_role('button', name='Enviar mensagem', exact=True).bounding_box()['y'] < 1000, 'Composer outside viewport'
                    page.get_by_role('textbox', name='Mensagem', exact=True).fill('Enviar turno sintético: ' + name)
                    states['typed'] = control_state(page)
                    assert states['typed']['send_disabled'] is False
                    page.get_by_role('button', name='Enviar mensagem', exact=True).click()
                    page.wait_for_function('document.querySelector(".shell-composer textarea")?.disabled === false')
                    page.get_by_text('Turno sintético recebido pelo HTTP de QA.', exact=True).wait_for()
                    states['after_send'] = control_state(page)
                    assert not any(row['pending_request_key'] for row in states['after_send']['drafts'])
                    sends = [row for row in backend.requests if row['action'] == 'message_send']
                    creates = [row for row in backend.requests if row['action'] == 'conversation_create']
                    assert len(sends) == 1, sends
                    assert sends[0]['request_key'] != 'qa-restored-request-key'
                    assert len(creates) == (1 if name in {'immediate', 'lost_creation', 'paginated_create', 'selected_in_home', 'native_bridge'} else 0)
                    if name in {'immediate', 'native_bridge'}:
                        assert page.evaluate('window.qaPendingFlashes') == 0, 'A normal acknowledged POST flashed global pending warning'
                    if name == 'native_bridge':
                        assert page.locator('[data-qa-native-controls=true]').count() == 1
                        assert page.evaluate('window.qaNativeCalls') == []
                    assert not errors, errors
                    page.screenshot(path=str(output / (name + '-1440.png')), full_page=True)
                except Exception as exc:
                    report['failures'].append(name + ': ' + str(exc)[:600])
                    page.screenshot(path=str(output / (name + '-failure.png')), full_page=True)
                finally:
                    backend.release_home.set()
                    report['scenarios'][name] = {'states': states, 'http_requests': backend.requests, 'page_errors': errors, 'console_errors': console_errors[:10]}
                    context.close(); server.shutdown(); server.server_close(); worker.join(timeout=3)
            browser.close()
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'report': str(output / 'report.json'), 'scenarios': list(report['scenarios']), 'failures': report['failures']}, ensure_ascii=True))
        return 1 if report['failures'] else 0
    finally:
        vite.terminate()
        try: vite.wait(timeout=10)
        except subprocess.TimeoutExpired: vite.kill(); vite.wait(timeout=5)
        log.close()


if __name__ == '__main__':
    raise SystemExit(main())
